from __future__ import annotations

from typing import Annotated, Optional

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.entities import CrawlRun, Document, Source, User
from app.services.crawl_events import list_recent, pick_current, request_cancel
from app.services.reindex import REINDEX_SOURCE_ID
from app.services.runtime_settings import resolved_settings

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health() -> dict:
    rs = resolved_settings()
    return {
        "ok": True,
        "app": rs.get("app_name"),
        "llm_provider": rs.get("llm_provider"),
        "dify_enabled": rs.get("dify_enabled"),
    }


@router.get("/ingest/status")
async def ingest_status(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    total = await db.scalar(select(func.count()).select_from(Document)) or 0
    ready = await db.scalar(select(func.count()).select_from(Document).where(Document.status == "ready")) or 0
    indexing = await db.scalar(
        select(func.count()).select_from(Document).where(Document.status == "indexing")
    ) or 0
    failed = await db.scalar(select(func.count()).select_from(Document).where(Document.status == "failed")) or 0
    stored = await db.scalar(select(func.count()).select_from(Document).where(Document.status == "stored")) or 0
    sources = (await db.scalars(select(Source).where(Source.id != REINDEX_SOURCE_ID))).all()
    from app.services.reindex import ensure_reindex_source

    await ensure_reindex_source(db)
    last_runs = (
        await db.scalars(select(CrawlRun).order_by(CrawlRun.started_at.desc()).limit(15))
    ).all()
    active = [r for r in last_runs if r.status == "running"]
    return {
        "documents": {
            "total": total,
            "ready": ready,
            "indexing": indexing,
            "stored": stored,
            "failed": failed,
        },
        "active": len(active) > 0,
        "sources": [
            {
                "id": s.id,
                "enabled": s.enabled,
                "last_crawl_at": s.last_crawl_at.isoformat() if s.last_crawl_at else None,
                "name_en": s.name_en,
                "name_zh_hk": s.name_zh_hk,
            }
            for s in sources
        ],
        "recent_runs": [await _run_status_payload(db, r) for r in last_runs],
    }


async def _run_status_payload(db: AsyncSession, run: CrawlRun) -> dict:
    events = await list_recent(db, run.id) if run.status == "running" else []
    job_type = "reindex" if run.source_id == REINDEX_SOURCE_ID else "crawl"
    return {
        "id": str(run.id),
        "source_id": run.source_id,
        "job_type": job_type,
        "status": run.status,
        "discovered": run.discovered,
        "downloaded": run.downloaded,
        "skipped": getattr(run, "skipped", 0) or 0,
        "failed": run.failed,
        "progress_message": run.progress_message,
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "current": pick_current(events),
        "recent_events": events,
        "cancel_requested": bool(run.cancel_requested),
    }


@router.post("/ingest/crawl/stop")
async def stop_crawl(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    run_id: Optional[str] = None,
) -> dict:
    """Request cancel and force-terminate active Celery crawl workers."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.models.entities import CrawlRun
    from app.worker import celery_app

    rid: UUID | None = None
    if run_id:
        try:
            rid = UUID(run_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid run_id",
            ) from exc

    n = await request_cancel(db, rid)

    # Soft-cancel alone only stops between files; terminate active crawl tasks now.
    revoked: list[str] = []
    try:
        inspect = celery_app.control.inspect(timeout=2.0)
        active = (inspect.active() if inspect else None) or {}
        reserved = (inspect.reserved() if inspect else None) or {}
        crawl_names = {
            "app.worker.crawl_all",
            "app.worker.crawl_source",
            "app.worker.reindex_all",
        }
        for bucket in (active, reserved):
            for _worker, tasks in bucket.items():
                for task in tasks or []:
                    if task.get("name") in crawl_names:
                        tid = task.get("id")
                        if tid and tid not in revoked:
                            celery_app.control.revoke(tid, terminate=True, signal="SIGTERM")
                            revoked.append(tid)
    except Exception:
        pass

    # Mark runs cancelled immediately so UI stops showing "running"
    stmt = select(CrawlRun).where(CrawlRun.status == "running")
    if rid is not None:
        stmt = stmt.where(CrawlRun.id == rid)
    rows = list((await db.scalars(stmt)).all())
    now = datetime.now(timezone.utc)
    for run in rows:
        run.status = "cancelled"
        run.cancel_requested = True
        run.progress_message = "Cancelled by user"
        run.finished_at = now
    if rows:
        await db.commit()

    return {"ok": True, "stopped": max(n, len(rows)), "revoked": len(revoked)}


@router.post("/ingest/crawl")
async def trigger_crawl(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    source_id: Optional[str] = None,
) -> dict:
    """Enqueue crawl on Celery worker so UI can poll live CrawlRun progress."""
    from app.worker import crawl_all, crawl_source

    running = await db.scalar(select(CrawlRun).where(CrawlRun.status == "running"))
    if running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A crawl or re-index job is already running",
        )

    if source_id:
        async_result = crawl_source.delay(source_id)
    else:
        async_result = crawl_all.delay()
    return {
        "ok": True,
        "started": True,
        "source_id": source_id,
        "task_id": async_result.id,
    }


@router.post("/ingest/reindex")
async def trigger_reindex(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    scope: str = "all",
) -> dict:
    """Enqueue full (or partial) re-index of stored documents with live progress."""
    from sqlalchemy import select

    from app.worker import reindex_all

    if scope not in ("all", "failed", "stored"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="scope must be all, failed, or stored",
        )

    running = await db.scalar(select(CrawlRun).where(CrawlRun.status == "running"))
    if running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A crawl or re-index job is already running",
        )

    async_result = reindex_all.delay(scope)
    return {
        "ok": True,
        "started": True,
        "scope": scope,
        "task_id": async_result.id,
    }


@router.post("/ingest/fix-metadata")
async def fix_metadata(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Repair titles / circular numbers / languages from stored file URLs and row text."""
    from app.services.fix_metadata import fix_document_metadata

    result = await fix_document_metadata(db)
    return {"ok": True, **result}


@router.post("/ingest/classify")
async def trigger_classify(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    force: bool = False,
    sync: bool = False,
) -> dict:
    """Backfill programme + topics. Default: Celery async; sync=1 runs inline (rules+LLM)."""
    from app.worker import classify_documents

    if sync:
        from app.services.classify import backfill_classifications

        result = await backfill_classifications(
            db, use_llm=True, force_topics=force
        )
        return {"ok": True, "started": False, "sync": True, **result}

    async_result = classify_documents.delay(force_topics=force, use_llm=True)
    return {
        "ok": True,
        "started": True,
        "force": force,
        "task_id": async_result.id,
    }
