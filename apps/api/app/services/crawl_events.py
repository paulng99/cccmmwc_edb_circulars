from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import CrawlEvent, CrawlRun

logger = logging.getLogger(__name__)

ORPHAN_RUN_REASON = "Interrupted by service restart — please crawl again"

_CURRENT_TYPES = (
    "classify_start",
    "index_start",
    "download_start",
    "page",
    "discovering",
)


def pick_current(events: list[dict]) -> dict | None:
    if not events:
        return None
    for event_type in _CURRENT_TYPES:
        for event in events:
            if event.get("event_type") == event_type:
                return event
    return None


def _event_to_dict(event: CrawlEvent) -> dict:
    return {
        "event_type": event.event_type,
        "url": event.url,
        "title": event.title,
        "source_id": event.source_id,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


async def emit_event(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    event_type: str,
    url: str | None = None,
    title: str | None = None,
    source_id: str | None = None,
) -> None:
    try:
        session.add(
            CrawlEvent(
                run_id=run_id,
                event_type=event_type,
                url=url,
                title=title,
                source_id=source_id,
            )
        )
        await session.commit()
    except Exception:
        logger.exception(
            "Failed to emit crawl event run_id=%s type=%s",
            run_id,
            event_type,
        )


async def list_recent(
    session: AsyncSession,
    run_id: uuid.UUID,
    limit: int = 40,
) -> list[dict]:
    result = await session.execute(
        select(CrawlEvent)
        .where(CrawlEvent.run_id == run_id)
        .order_by(CrawlEvent.created_at.desc())
        .limit(limit)
    )
    return [_event_to_dict(event) for event in result.scalars().all()]


def format_exception(exc: BaseException) -> str:
    """Include the exception type and cause.

    httpx connection errors often have an empty ``str()``; the useful text
    is the class name and ``__cause__``.
    """
    parts = [type(exc).__name__]
    message = str(exc).strip()
    if message and message != type(exc).__name__:
        parts.append(message)
    cause = exc.__cause__ or exc.__context__
    if cause is not None and cause is not exc:
        cause_message = str(cause).strip() or type(cause).__name__
        parts.append(f"cause={cause_message}")
    return ": ".join(parts)[:4000]


async def close_orphaned_runs(session: AsyncSession, *, reason: str) -> int:
    """Mark every ``running`` crawl as failed.

    Call this when the worker process starts. A previous process may have
    been killed mid-run; those rows otherwise stay ``running`` and the
    status page keeps showing a progress bar that never moves.
    """
    now = datetime.now(timezone.utc)
    result = await session.execute(
        update(CrawlRun)
        .where(CrawlRun.status == "running")
        .values(
            status="failed",
            error_message=reason[:4000],
            progress_message=reason[:2000],
            finished_at=now,
        )
    )
    await session.commit()
    return int(result.rowcount or 0)


async def request_cancel(
    session: AsyncSession,
    run_id: uuid.UUID | None,
) -> int:
    stmt = (
        update(CrawlRun)
        .where(CrawlRun.status == "running")
        .values(cancel_requested=True)
    )
    if run_id is not None:
        stmt = stmt.where(CrawlRun.id == run_id)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount
