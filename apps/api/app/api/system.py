from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.db import SessionLocal, get_db
from app.models.entities import CrawlRun, Document, Source, User
from app.services.pipeline import run_source_crawl

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    return {
        "ok": True,
        "app": settings.app_name,
        "llm_provider": settings.llm_provider,
        "dify_enabled": settings.dify_enabled,
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
    sources = (await db.scalars(select(Source))).all()
    last_runs = (
        await db.scalars(select(CrawlRun).order_by(CrawlRun.started_at.desc()).limit(10))
    ).all()
    return {
        "documents": {"total": total, "ready": ready, "indexing": indexing, "failed": failed},
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
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in last_runs
        ],
    }


async def _bg_crawl(source_id: Optional[str]) -> None:
    async with SessionLocal() as session:
        await run_source_crawl(session, source_id=source_id)


@router.post("/ingest/crawl")
async def trigger_crawl(
    background: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    source_id: Optional[str] = None,
) -> dict:
    background.add_task(_bg_crawl, source_id)
    return {"ok": True, "started": True, "source_id": source_id}
