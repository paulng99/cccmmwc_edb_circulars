"""Full-library LLM backfill for activity start/deadline dates.

Local regex extraction is voided for display and backfill. While backfill is
in progress, calendar APIs expose dates_updating so the UI can show「日期更新中」.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.entities import AppSetting, Document, DocumentChunk
from app.services.llm_activities import (
    ACTIVITIES_PARSED_FLAG,
    BACKFILL_CURRENT_KEY,
    BACKFILL_DONE_KEY,
    BACKFILL_STATUS_DONE,
    BACKFILL_STATUS_IN_PROGRESS,
    BACKFILL_STATUS_KEY,
    BACKFILL_TOTAL_KEY,
    refresh_activities_llm_only,
)

# Re-export status helpers for API/tests.
__all__ = [
    "ACTIVITIES_PARSED_FLAG",
    "BACKFILL_INTER_DOC_DELAY_SECONDS",
    "BACKFILL_STATUS_DONE",
    "BACKFILL_STATUS_IN_PROGRESS",
    "BACKFILL_STATUS_KEY",
    "backfill_document_activities",
    "dates_progress_from_values",
    "dates_updating_from_values",
    "get_dates_status",
    "get_dates_updating",
    "prepare_llm_activity_backfill",
]

_MISSING = object()

logger = logging.getLogger(__name__)

_CHUNK_LIMIT = 12
# Sequential backfill only; pause between documents so full-library boot/ingest
# does not hammer the answer-model LLM.
BACKFILL_INTER_DOC_DELAY_SECONDS = 1.0


def dates_updating_from_values(values: dict[str, Any] | None) -> bool:
    if not isinstance(values, dict):
        return False
    return values.get(BACKFILL_STATUS_KEY) == BACKFILL_STATUS_IN_PROGRESS


def _as_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 0
    try:
        count = int(value)
    except ValueError:
        return 0
    return max(count, 0)


def dates_progress_from_values(values: dict[str, Any] | None) -> dict[str, Any] | None:
    """Live backfill counts while status is in_progress. None once dates are ready."""
    if not dates_updating_from_values(values) or not isinstance(values, dict):
        return None
    done = _as_count(values.get(BACKFILL_DONE_KEY))
    total = _as_count(values.get(BACKFILL_TOTAL_KEY))
    if total > 0 and done > total:
        done = total
    current = values.get(BACKFILL_CURRENT_KEY)
    label = current.strip()[:200] if isinstance(current, str) and current.strip() else None
    return {"done": done, "total": total, "current": label}


async def _load_settings_row(session: AsyncSession) -> AppSetting:
    row = await session.get(AppSetting, 1)
    if row is None:
        row = AppSetting(id=1, values={})
        session.add(row)
        await session.flush()
    return row


async def _set_backfill_status(
    session: AsyncSession,
    status: str,
    *,
    done: int | None = None,
    total: int | None = None,
    current: str | None | object = _MISSING,
) -> AppSetting:
    row = await _load_settings_row(session)
    values = dict(row.values or {})
    values[BACKFILL_STATUS_KEY] = status
    if done is not None:
        values[BACKFILL_DONE_KEY] = done
    if total is not None:
        values[BACKFILL_TOTAL_KEY] = total
    if current is not _MISSING:
        if isinstance(current, str) and current.strip():
            values[BACKFILL_CURRENT_KEY] = current.strip()[:200]
        else:
            values.pop(BACKFILL_CURRENT_KEY, None)
    row.values = values
    if hasattr(row, "_sa_instance_state"):
        flag_modified(row, "values")
    return row


def _progress_label(doc: object) -> str | None:
    circular = str(getattr(doc, "circular_no", None) or "").strip()
    title = str(getattr(doc, "title", None) or "").strip()
    if circular and title:
        label = f"{circular} · {title}"
    else:
        label = circular or title
    return label[:200] if label else None


async def get_dates_updating(session: AsyncSession) -> bool:
    row = await session.get(AppSetting, 1)
    return dates_updating_from_values(row.values if row else None)


async def get_dates_status(session: AsyncSession) -> dict[str, Any]:
    row = await session.get(AppSetting, 1)
    values = row.values if row else None
    updating = dates_updating_from_values(values)
    return {
        "dates_updating": updating,
        "dates_progress": dates_progress_from_values(values) if updating else None,
    }


async def _docs_needing_llm_activities(session: AsyncSession) -> list[Document]:
    parsed = Document.extra["activities_parsed"].astext
    return list(
        (
            await session.scalars(
                select(Document).where(
                    or_(parsed.is_(None), parsed != ACTIVITIES_PARSED_FLAG)
                )
            )
        ).all()
    )


async def _body_for_doc(session: AsyncSession, doc: Document) -> str:
    chunks = (
        await session.execute(
            select(DocumentChunk.content)
            .where(
                DocumentChunk.document_id == doc.id,
                DocumentChunk.chunk_index < _CHUNK_LIMIT,
            )
            .order_by(DocumentChunk.chunk_index)
        )
    ).all()
    parts = [str(row[0]) for row in chunks if row[0]]
    return "\n".join(parts)


async def prepare_llm_activity_backfill(session: AsyncSession) -> dict[str, int]:
    """Clear stale local regex activities and mark backfill in progress.

    Safe to call on every boot: no-op when every document is already llm-1 and
    status is done.
    """
    docs = await _docs_needing_llm_activities(session)
    if not docs:
        await _set_backfill_status(
            session, BACKFILL_STATUS_DONE, done=0, total=0, current=None
        )
        await session.commit()
        return {"cleared": 0, "pending": 0}

    await _set_backfill_status(
        session,
        BACKFILL_STATUS_IN_PROGRESS,
        done=0,
        total=len(docs),
        current=None,
    )
    cleared = 0
    for doc in docs:
        if doc.activities:
            doc.activities = []
            if hasattr(doc, "_sa_instance_state"):
                flag_modified(doc, "activities")
            cleared += 1
    await session.commit()
    logger.info(
        "LLM activity backfill prepared pending=%s cleared=%s",
        len(docs),
        cleared,
    )
    return {"cleared": cleared, "pending": len(docs)}


async def backfill_document_activities(session: AsyncSession) -> dict[str, int]:
    """Run LLM date extraction for every document not yet at llm-1."""
    docs = await _docs_needing_llm_activities(session)
    if not docs:
        await _set_backfill_status(
            session, BACKFILL_STATUS_DONE, done=0, total=0, current=None
        )
        await session.commit()
        return {"checked": 0, "updated": 0}

    updated = 0
    total = len(docs)
    for index, doc in enumerate(docs):
        await _set_backfill_status(
            session,
            BACKFILL_STATUS_IN_PROGRESS,
            done=index,
            total=total,
            current=_progress_label(doc),
        )
        await session.commit()
        text = await _body_for_doc(session, doc)
        if await refresh_activities_llm_only(doc, text):
            updated += 1
        await _set_backfill_status(
            session,
            BACKFILL_STATUS_IN_PROGRESS,
            done=index + 1,
            total=total,
        )
        await session.commit()
        if index + 1 < total and BACKFILL_INTER_DOC_DELAY_SECONDS > 0:
            await asyncio.sleep(BACKFILL_INTER_DOC_DELAY_SECONDS)

    # Re-check in case new docs arrived mid-run.
    remaining = await _docs_needing_llm_activities(session)
    if not remaining:
        await _set_backfill_status(
            session, BACKFILL_STATUS_DONE, done=total, total=total, current=None
        )
        await session.commit()

    logger.info(
        "LLM activity backfill checked=%s updated=%s remaining=%s",
        len(docs),
        updated,
        len(remaining),
    )
    return {"checked": len(docs), "updated": updated}
