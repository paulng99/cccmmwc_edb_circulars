from __future__ import annotations

import asyncio
import logging
from typing import Any

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

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
    """Run an async coroutine in a fresh event loop.

    Celery prefork workers call this once per task. The module-level async
    SQLAlchemy engine keeps a connection pool; connections created on loop N
    cannot be reused on loop N+1 ("attached to a different loop"). Dispose the
    pool before and after each run so every task gets a clean loop binding.
    """
    from app.core.db import engine

    # Drop pooled connections tied to a previous (now closed) loop without
    # awaiting their async close — that would fail with "Event loop is closed".
    engine.sync_engine.dispose(close=False)

    async def _wrapped() -> Any:
        try:
            return await coro
        finally:
            await engine.dispose()

    return asyncio.run(_wrapped())


@worker_ready.connect
def _close_orphaned_crawl_runs(**_kwargs: object) -> None:
    """A killed worker leaves CrawlRun.status='running'. Close those rows."""
    from app.core.db import SessionLocal
    from app.services.crawl_events import ORPHAN_RUN_REASON, close_orphaned_runs

    async def _inner() -> int:
        async with SessionLocal() as session:
            return await close_orphaned_runs(session, reason=ORPHAN_RUN_REASON)

    try:
        closed = _run_async(_inner())
    except Exception:
        logger.exception("failed to close orphaned crawl runs")
        return
    if closed:
        logger.warning("closed %s orphaned crawl run(s) after worker start", closed)


async def _refresh_runtime_settings(session) -> None:
    from app.services.runtime_settings import ensure_seeded, get_merged, invalidate_cache

    invalidate_cache()
    await ensure_seeded(session)
    await get_merged(session)


@celery_app.task(name="app.worker.crawl_all")
def crawl_all(user_id: str | None = None) -> dict:
    from app.core.db import SessionLocal
    from app.services.pipeline import run_source_crawl
    from app.services.usage import usage_user_ref

    async def _inner() -> dict:
        async with SessionLocal() as session:
            await _refresh_runtime_settings(session)
            with usage_user_ref(user_id):
                return await run_source_crawl(session)

    return _run_async(_inner())


@celery_app.task(name="app.worker.crawl_source")
def crawl_source(source_id: str, user_id: str | None = None) -> dict:
    from app.core.db import SessionLocal
    from app.services.pipeline import run_source_crawl
    from app.services.usage import usage_user_ref

    async def _inner() -> dict:
        async with SessionLocal() as session:
            await _refresh_runtime_settings(session)
            with usage_user_ref(user_id):
                return await run_source_crawl(session, source_id=source_id)

    return _run_async(_inner())


@celery_app.task(name="app.worker.reindex_all")
def reindex_all(scope: str = "all", user_id: str | None = None) -> dict:
    from app.core.db import SessionLocal
    from app.services.reindex import run_reindex_all
    from app.services.usage import usage_user_ref

    async def _inner() -> dict:
        async with SessionLocal() as session:
            await _refresh_runtime_settings(session)
            with usage_user_ref(user_id):
                return await run_reindex_all(session, scope=scope)

    return _run_async(_inner())


@celery_app.task(name="app.worker.index_document")
def index_document_task(document_id: str) -> dict:
    import uuid

    from app.core.db import SessionLocal
    from app.services.rag import index_document

    async def _inner() -> dict:
        async with SessionLocal() as session:
            await _refresh_runtime_settings(session)
            return await index_document(session, uuid.UUID(document_id))

    return _run_async(_inner())


@celery_app.task(name="app.worker.classify_documents")
def classify_documents(force_topics: bool = False, use_llm: bool = True, user_id: str | None = None) -> dict:
    from app.core.db import SessionLocal
    from app.services.classify import backfill_classifications
    from app.services.usage import usage_user_ref

    async def _inner() -> dict:
        async with SessionLocal() as session:
            await _refresh_runtime_settings(session)
            with usage_user_ref(user_id):
                return await backfill_classifications(
                    session, use_llm=use_llm, force_topics=force_topics
                )

    return _run_async(_inner())
