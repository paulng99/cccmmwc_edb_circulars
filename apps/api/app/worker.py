from __future__ import annotations

import asyncio
from typing import Any

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "edb_circulars",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.timezone = "Asia/Hong_Kong"
celery_app.conf.beat_schedule = {
    "daily-crawl-all": {
        "task": "app.worker.crawl_all",
        "schedule": crontab(hour=6, minute=0),
    },
}


def _run_async(coro: Any) -> Any:
    return asyncio.run(coro)


@celery_app.task(name="app.worker.crawl_all")
def crawl_all() -> dict:
    from app.core.db import SessionLocal
    from app.services.pipeline import run_source_crawl

    async def _inner() -> dict:
        async with SessionLocal() as session:
            return await run_source_crawl(session)

    return _run_async(_inner())


@celery_app.task(name="app.worker.crawl_source")
def crawl_source(source_id: str) -> dict:
    from app.core.db import SessionLocal
    from app.services.pipeline import run_source_crawl

    async def _inner() -> dict:
        async with SessionLocal() as session:
            return await run_source_crawl(session, source_id=source_id)

    return _run_async(_inner())


@celery_app.task(name="app.worker.index_document")
def index_document_task(document_id: str) -> dict:
    import uuid

    from app.core.db import SessionLocal
    from app.services.rag import index_document

    async def _inner() -> dict:
        async with SessionLocal() as session:
            return await index_document(session, uuid.UUID(document_id))

    return _run_async(_inner())
