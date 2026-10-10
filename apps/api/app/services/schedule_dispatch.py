"""Dispatch per-source crawls when sources.yaml schedules match (Asia/Hong_Kong)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import celery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.registry import get_enabled_sources
from app.models.entities import CrawlRun
from app.services.cron_match import cron_matches
from app.services.runtime_settings import resolved_settings

logger = logging.getLogger(__name__)
HK = ZoneInfo("Asia/Hong_Kong")


def sources_due_at(sources: list[dict[str, Any]], when: datetime) -> list[dict[str, Any]]:
    """Enabled sources whose cron matches ``when``, sorted by priority then id."""
    due: list[dict[str, Any]] = []
    for src in sources:
        if not src.get("enabled"):
            continue
        schedule = src.get("schedule")
        if not isinstance(schedule, str) or not schedule.strip():
            continue
        try:
            if cron_matches(schedule, when):
                due.append(src)
        except ValueError:
            logger.warning("invalid schedule for source %s: %r", src.get("id"), schedule)
    return sorted(due, key=lambda s: (int(s.get("priority") or 0), str(s.get("id") or "")))


async def source_ids_blocked(session: AsyncSession, source_ids: list[str], minute_start: datetime) -> set[str]:
    """Sources with a running crawl, or any crawl started in the current minute."""
    if not source_ids:
        return set()
    rows = await session.execute(
        select(CrawlRun.source_id).where(
            CrawlRun.source_id.in_(source_ids),
            (CrawlRun.status == "running") | (CrawlRun.started_at >= minute_start),
        )
    )
    return {row[0] for row in rows.all()}


async def dispatch_scheduled_crawls(session: AsyncSession, *, now: datetime | None = None) -> dict:
    """Enqueue ``crawl_source`` for each due source. Skip if crawl_enabled is false or already busy."""
    rs = await resolved_settings(session)
    if not rs.get("crawl_enabled", True):
        return {
            "status": "skipped",
            "reason": "crawl_disabled",
            "enqueued": [],
            "skipped_busy": [],
            "due": [],
        }

    when = now.astimezone(HK) if now is not None else datetime.now(HK)
    minute_start = when.replace(second=0, microsecond=0)
    due_sources = sources_due_at(get_enabled_sources(), when)
    due_ids = [str(s["id"]) for s in due_sources]
    blocked = await source_ids_blocked(session, due_ids, minute_start)

    enqueued: list[str] = []
    skipped_busy: list[str] = []
    for sid in due_ids:
        if sid in blocked:
            skipped_busy.append(sid)
            continue
        celery.current_app.send_task("app.worker.crawl_source", args=[sid])
        enqueued.append(sid)

    return {
        "status": "ok",
        "at": minute_start.isoformat(),
        "due": due_ids,
        "enqueued": enqueued,
        "skipped_busy": skipped_busy,
    }
