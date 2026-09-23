"""Batch re-index all stored documents with live CrawlRun progress."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import CrawlRun, Document, Source
from app.services.crawl_events import emit_event
from app.services.pipeline import _save_run_progress
from app.services.rag import index_document

REINDEX_SOURCE_ID = "system_reindex"


async def ensure_reindex_source(session: AsyncSession) -> None:
    src = await session.get(Source, REINDEX_SOURCE_ID)
    if src:
        return
    session.add(
        Source(
            id=REINDEX_SOURCE_ID,
            name_en="Re-index all documents",
            name_zh_hk="全部文件重新索引",
            enabled=False,
            type="system",
            base_url="",
            config={},
        )
    )
    await session.commit()


async def run_reindex_all(session: AsyncSession, *, scope: str = "all") -> dict:
    """Re-index documents. scope: all | failed | stored."""
    await ensure_reindex_source(session)

    running = await session.scalar(select(CrawlRun).where(CrawlRun.status == "running"))
    if running:
        return {"ok": False, "reason": "already_running", "run_id": str(running.id)}

    stmt = select(Document).where(Document.storage_key.is_not(None)).order_by(
        Document.issued_at.desc().nullslast(),
        Document.created_at.desc(),
    )
    if scope == "failed":
        stmt = stmt.where(Document.status.in_(("failed", "stored", "indexing")))
    elif scope == "stored":
        stmt = stmt.where(Document.status == "stored")

    docs = list((await session.scalars(stmt)).all())
    total = len(docs)

    run = CrawlRun(
        source_id=REINDEX_SOURCE_ID,
        status="running",
        discovered=total,
        downloaded=0,
        failed=0,
        progress_message=f"Re-indexing {total} documents…",
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    await emit_event(
        session,
        run_id=run.id,
        event_type="discovering",
        title=f"{total} documents to index",
        source_id=REINDEX_SOURCE_ID,
    )

    indexed = 0
    failed = 0
    cancelled = False

    for i, doc in enumerate(docs, start=1):
        run = await session.get(CrawlRun, run.id)
        if run and run.cancel_requested:
            run.status = "cancelled"
            run.progress_message = "Cancelled by user"
            run.finished_at = datetime.now(timezone.utc)
            await emit_event(
                session,
                run_id=run.id,
                event_type="cancelled",
                source_id=REINDEX_SOURCE_ID,
            )
            await session.commit()
            cancelled = True
            break

        label = (doc.circular_no or doc.title or str(doc.id))[:120]
        await emit_event(
            session,
            run_id=run.id,
            event_type="index_start",
            url=doc.file_url,
            title=label,
            source_id=doc.source_id,
        )

        try:
            result = await index_document(session, doc.id)
            if result.get("ok"):
                indexed += 1
                await emit_event(
                    session,
                    run_id=run.id,
                    event_type="index_ok",
                    url=doc.file_url,
                    title=label,
                    source_id=doc.source_id,
                )
            else:
                failed += 1
                await emit_event(
                    session,
                    run_id=run.id,
                    event_type="index_fail",
                    url=doc.file_url,
                    title=label,
                    source_id=doc.source_id,
                )
        except Exception as exc:
            failed += 1
            await emit_event(
                session,
                run_id=run.id,
                event_type="index_fail",
                url=doc.file_url,
                title=f"{label}: {exc}"[:200],
                source_id=doc.source_id,
            )

        if i % 2 == 0 or i == total:
            await _save_run_progress(
                session,
                run,
                discovered=total,
                downloaded=indexed,
                failed=failed,
                message=f"Indexed {indexed}/{total} · Failed {failed}",
            )

    if not cancelled:
        run = await session.get(CrawlRun, run.id)
        if run:
            run.status = "completed"
            run.discovered = total
            run.downloaded = indexed
            run.failed = failed
            run.progress_message = f"Done: indexed {indexed}, failed {failed}"
            run.finished_at = datetime.now(timezone.utc)
            await emit_event(
                session,
                run_id=run.id,
                event_type="done",
                title=f"Indexed {indexed} · Failed {failed}",
                source_id=REINDEX_SOURCE_ID,
            )
            await session.commit()

    return {
        "ok": True,
        "cancelled": cancelled,
        "run_id": str(run.id) if run else None,
        "total": total,
        "indexed": indexed,
        "failed": failed,
    }
