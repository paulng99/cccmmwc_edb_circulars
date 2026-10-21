"""Dispatch per-source crawls when sources.yaml schedules match (Asia/Hong_Kong)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.registry import get_enabled_sources, resolve_sources_config_path
from app.core.config import get_settings
from app.models.entities import CrawlRun
from app.services.cron_match import cron_matches
from app.services.runtime_settings import resolved_settings
from app.services.schedule_dispatch_state import (
    load_last_dispatch,
    parse_checked_to,
    persist_last_dispatch,
)

logger = logging.getLogger(__name__)
HK = ZoneInfo("Asia/Hong_Kong")

# When the worker was busy past a cron minute, still match slots since the last
# successful dispatch check (capped so a long outage does not enqueue a stampede).
CATCH_UP_MAX_MINUTES = 24 * 60
# If Redis has never stored a watermark, only look this far back (avoid mass enqueue on deploy).
DEFAULT_LOOKBACK_MINUTES = 60


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


def catch_up_window(
    minute_now: datetime,
    *,
    last_checked: datetime | None,
    default_lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
    max_minutes: int = CATCH_UP_MAX_MINUTES,
) -> datetime:
    """Return inclusive window start (HK wall minute) for cron catch-up."""
    minute_now = minute_now.astimezone(HK).replace(second=0, microsecond=0)
    earliest = minute_now - timedelta(minutes=max_minutes)
    if last_checked is None:
        start = minute_now - timedelta(minutes=default_lookback_minutes)
    else:
        # Resume from the minute after the last completed check.
        start = last_checked.astimezone(HK).replace(second=0, microsecond=0) + timedelta(minutes=1)
    if start < earliest:
        start = earliest
    if start > minute_now:
        start = minute_now
    return start


def sources_due_between(
    sources: list[dict[str, Any]],
    window_start: datetime,
    minute_now: datetime,
) -> list[str]:
    """Source ids due on any minute in ``[window_start, minute_now]`` (priority order)."""
    window_start = window_start.astimezone(HK).replace(second=0, microsecond=0)
    minute_now = minute_now.astimezone(HK).replace(second=0, microsecond=0)
    due_meta: dict[str, dict[str, Any]] = {}
    t = window_start
    while t <= minute_now:
        for src in sources_due_at(sources, t):
            sid = str(src["id"])
            if sid not in due_meta:
                due_meta[sid] = src
        t += timedelta(minutes=1)
    ordered = sorted(
        due_meta.values(),
        key=lambda s: (int(s.get("priority") or 0), str(s.get("id") or "")),
    )
    return [str(s["id"]) for s in ordered]


async def source_ids_blocked(session: AsyncSession, source_ids: list[str], minute_start: datetime) -> set[str]:
    """Sources with a running crawl, or any crawl started at/after ``minute_start``."""
    if not source_ids:
        return set()
    rows = await session.execute(
        select(CrawlRun.source_id).where(
            CrawlRun.source_id.in_(source_ids),
            (CrawlRun.status == "running") | (CrawlRun.started_at >= minute_start),
        )
    )
    return {row[0] for row in rows.all()}


def _enqueue_crawl_source(source_id: str) -> str:
    """Enqueue via the bound Celery task (not celery.current_app)."""
    # Lazy import: app.worker imports this module inside the task body.
    from app.worker import crawl_source

    async_result = crawl_source.delay(source_id)
    return str(async_result.id)


def _sources_path_meta() -> dict[str, Any]:
    try:
        path = resolve_sources_config_path(get_settings().sources_config_path)
        return {
            "sources_path": str(path),
            "sources_mtime": path.stat().st_mtime if path.exists() else None,
        }
    except Exception as exc:
        return {"sources_path": None, "sources_error": str(exc)}


async def dispatch_scheduled_crawls(session: AsyncSession, *, now: datetime | None = None) -> dict:
    """Enqueue ``crawl_source`` for each due source. Skip if crawl_enabled is false or already busy.

    Cron matching uses Asia/Hong_Kong. If the Celery worker runs this task after the
    exact cron minute (e.g. concurrency=1 while a crawl was still running), we still
    match schedules for every minute since the last successful check (capped).
    """
    path_meta = _sources_path_meta()
    rs = await resolved_settings(session)
    if not rs.get("crawl_enabled", True):
        result = {
            "status": "skipped",
            "reason": "crawl_disabled",
            "enqueued": [],
            "skipped_busy": [],
            "due": [],
            "checked_from": None,
            "checked_to": None,
            "at": None,
            **path_meta,
        }
        logger.info(
            "schedule dispatch skipped crawl_disabled path=%s",
            path_meta.get("sources_path"),
        )
        persist_last_dispatch(result)
        return result

    when = now.astimezone(HK) if now is not None else datetime.now(HK)
    minute_now = when.replace(second=0, microsecond=0)
    last_checked = parse_checked_to(load_last_dispatch())
    window_start = catch_up_window(minute_now, last_checked=last_checked)

    sources = get_enabled_sources()
    due_ids = sources_due_between(sources, window_start, minute_now)
    blocked = await source_ids_blocked(session, due_ids, window_start)

    enqueued: list[str] = []
    skipped_busy: list[str] = []
    task_ids: dict[str, str] = {}
    errors: list[str] = []
    for sid in due_ids:
        if sid in blocked:
            skipped_busy.append(sid)
            continue
        try:
            task_ids[sid] = _enqueue_crawl_source(sid)
            enqueued.append(sid)
        except Exception as exc:
            logger.exception("failed to enqueue crawl_source for %s", sid)
            errors.append(f"{sid}: {exc}")

    status = "ok" if not errors else ("error" if not enqueued else "ok")
    result = {
        "status": status,
        "at": minute_now.isoformat(),
        "checked_from": window_start.isoformat(),
        "checked_to": minute_now.isoformat(),
        "due": due_ids,
        "enqueued": enqueued,
        "skipped_busy": skipped_busy,
        "task_ids": task_ids,
        "sources_count": len(sources),
        **path_meta,
    }
    if errors:
        result["errors"] = errors
        result["error"] = errors[0]

    logger.info(
        "schedule dispatch status=%s due=%s enqueued=%s skipped_busy=%s "
        "checked_from=%s checked_to=%s path=%s",
        result["status"],
        due_ids,
        enqueued,
        skipped_busy,
        window_start.isoformat(),
        minute_now.isoformat(),
        path_meta.get("sources_path"),
    )
    persist_last_dispatch(result)
    return result
