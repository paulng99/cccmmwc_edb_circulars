from __future__ import annotations

import mimetypes
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.base import DiscoveredItem, get_collector
from app.collectors.registry import get_enabled_sources, load_sources_config
from app.models.entities import CrawlRun, Document, Source
from app.services.rag import index_document
from app.services.runtime_settings import get_merged, resolved_settings
from app.services.storage import content_hash, put_object


async def sync_sources_table(session: AsyncSession) -> None:
    for cfg in load_sources_config():
        src = await session.get(Source, cfg["id"])
        name = cfg.get("name") or {}
        if not src:
            src = Source(
                id=cfg["id"],
                name_en=name.get("en") or cfg["id"],
                name_zh_hk=name.get("zh-HK") or name.get("en") or cfg["id"],
                enabled=bool(cfg.get("enabled", True)),
                type=cfg["type"],
                base_url=cfg.get("base_url") or "",
                config=cfg,
            )
            session.add(src)
        else:
            src.name_en = name.get("en") or src.name_en
            src.name_zh_hk = name.get("zh-HK") or src.name_zh_hk
            src.enabled = bool(cfg.get("enabled", True))
            src.type = cfg["type"]
            src.base_url = cfg.get("base_url") or src.base_url
            src.config = cfg
    await session.commit()


async def download_and_store(
    session: AsyncSession,
    source_id: str,
    item: DiscoveredItem,
) -> Document | None:
    rs = resolved_settings()
    headers = {"User-Agent": rs["crawl_user_agent"]}
    async with httpx.AsyncClient(headers=headers, timeout=120, follow_redirects=True) as client:
        resp = await client.get(item.file_url)
        if resp.status_code >= 400:
            return None
        data = resp.content
        if not data:
            return None

    digest = content_hash(data)
    existing = await session.scalar(select(Document).where(Document.content_hash == digest))
    if existing:
        # Refresh metadata if an older crawl stored language-label titles
        from app.collectors.circular_meta import is_language_label

        changed = False
        if item.title and (is_language_label(existing.title) or not existing.title):
            existing.title = item.title[:1000]
            changed = True
        if item.circular_no and item.circular_no != existing.circular_no:
            existing.circular_no = item.circular_no
            changed = True
        if item.language and item.language != existing.language:
            existing.language = item.language
            changed = True
        if item.issued_at and existing.issued_at != item.issued_at:
            existing.issued_at = item.issued_at
            changed = True
        if item.meta:
            extra = dict(existing.extra or {})
            extra.update(item.meta)
            existing.extra = extra
            changed = True
        if changed:
            await session.commit()
            await session.refresh(existing)
        return existing

    mime = item.mime_type
    guessed, _ = mimetypes.guess_type(item.file_url)
    if guessed:
        mime = guessed
    ext = PurePosixPath(urlparse(item.file_url).path).suffix or ".pdf"
    key = f"{source_id}/{digest[:2]}/{digest}{ext}"
    put_object(key, data, content_type=mime)

    doc = Document(
        source_id=source_id,
        title=item.title,
        circular_no=item.circular_no,
        issued_at=item.issued_at,
        language=item.language,
        source_url=item.source_url,
        file_url=item.file_url,
        mime_type=mime,
        content_hash=digest,
        storage_key=key,
        file_size=len(data),
        status="stored",
        extra=item.meta or {},
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return doc


async def _save_run_progress(
    session: AsyncSession,
    run: CrawlRun,
    *,
    discovered: int,
    downloaded: int,
    failed: int,
    message: str | None = None,
) -> None:
    run.discovered = discovered
    run.downloaded = downloaded
    run.failed = failed
    if message is not None:
        run.progress_message = message[:2000]
    await session.commit()


async def run_source_crawl(session: AsyncSession, source_id: str | None = None) -> dict:
    await sync_sources_table(session)
    sources = get_enabled_sources()
    if source_id:
        sources = [s for s in sources if s["id"] == source_id]
    summary = {"runs": []}

    for cfg in sources:
        run = CrawlRun(
            source_id=cfg["id"],
            status="running",
            progress_message="Discovering files…",
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        discovered = 0
        downloaded = 0
        failed = 0
        try:
            collector = get_collector(cfg["type"])
            items = await collector.discover(cfg)
            discovered = len(items)
            await _save_run_progress(
                session,
                run,
                discovered=discovered,
                downloaded=0,
                failed=0,
                message=f"Discovered {discovered} files, downloading…",
            )

            for i, item in enumerate(items, start=1):
                label = (item.circular_no or item.title or item.file_url or "")[:120]
                try:
                    doc = await download_and_store(session, cfg["id"], item)
                    if doc:
                        downloaded += 1
                        if doc.status in ("stored", "failed"):
                            result = await index_document(session, doc.id)
                            if not result.get("ok"):
                                failed += 1
                    else:
                        failed += 1
                except Exception:
                    await session.rollback()
                    failed += 1
                    run = await session.get(CrawlRun, run.id) or run

                if i % 3 == 0 or i == discovered:
                    await _save_run_progress(
                        session,
                        run,
                        discovered=discovered,
                        downloaded=downloaded,
                        failed=failed,
                        message=f"[{i}/{discovered}] {label}",
                    )

            run.status = "completed"
            run.progress_message = f"Done — downloaded {downloaded}, failed {failed}"
            src = await session.get(Source, cfg["id"])
            if src:
                src.last_crawl_at = datetime.now(timezone.utc)
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            run = await session.get(CrawlRun, run.id)
            if run:
                run.status = "failed"
                run.error_message = str(exc)[:4000]
                run.progress_message = f"Failed: {exc}"[:2000]
            failed += 1
        if run:
            run.discovered = discovered
            run.downloaded = downloaded
            run.failed = failed
            run.finished_at = datetime.now(timezone.utc)
            await session.commit()
            summary["runs"].append(
                {
                    "source_id": cfg["id"],
                    "run_id": str(run.id),
                    "status": run.status,
                    "discovered": discovered,
                    "downloaded": downloaded,
                    "failed": failed,
                }
            )
    return summary
