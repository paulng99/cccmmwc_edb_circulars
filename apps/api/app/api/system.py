from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.entities import CrawlRun, Document, Source, User
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
    sources = (await db.scalars(select(Source))).all()
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
        "recent_runs": [
            {
                "id": str(r.id),
                "source_id": r.source_id,
                "status": r.status,
                "discovered": r.discovered,
                "downloaded": r.downloaded,
                "failed": r.failed,
                "progress_message": r.progress_message,
                "error_message": r.error_message,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in last_runs
        ],
    }


@router.post("/ingest/crawl")
async def trigger_crawl(
    user: Annotated[User, Depends(get_current_user)],
    source_id: Optional[str] = None,
) -> dict:
    """Enqueue crawl on Celery worker so UI can poll live CrawlRun progress."""
    from app.worker import crawl_all, crawl_source

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


@router.post("/ingest/fix-metadata")
async def fix_metadata(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Repair titles / circular numbers / languages from stored file URLs and row text."""
    from app.services.fix_metadata import fix_document_metadata

    result = await fix_document_metadata(db)
    return {"ok": True, **result}
