"""Document programme + topic classification (rules first, LLM fallback)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import CrawlRun, Document, Source
from app.services.crawl_events import emit_event
from app.services.llm import get_llm_client
from app.services.pipeline import _save_run_progress
from app.services.usage import usage_scope

logger = logging.getLogger(__name__)

CLASSIFY_SOURCE_ID = "system_classify"

PROGRAMMES = frozenset({"circular", "sister_school", "lwlssg", "other"})
TOPICS = frozenset(
    {
        "grant_funding",
        "curriculum",
        "admin",
        "student_activity",
        "parent_home",
        "other",
    }
)

_CIRCULAR_SOURCES = frozenset({"edb_circulars"})
_PROGRAMME_BY_SOURCE = {
    "edb_circulars": "circular",
    "sss_sister": "sister_school",
    "edb_lwlssg": "lwlssg",
}

# Keyword rules: topic -> patterns (zh + en). First matches win; multiple allowed.
_TOPIC_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "grant_funding",
        re.compile(
            r"津貼|撥款|補助金|grant|funding|subsidy|LWLSSG|"
            r"姊妹學校津貼|全方位學習.*津貼|運用津貼|津貼運用|"
            r"一筆過撥款|經常津貼|非經常津貼",
            re.I,
        ),
    ),
    (
        "parent_home",
        re.compile(
            r"家長|家校|錦囊|parent|home.?school|家長會|家長教育",
            re.I,
        ),
    ),
    (
        "curriculum",
        re.compile(
            r"課程|評估|學習領域|課程及評估|curriculum|assessment|"
            r"學與教|教科書|考評|諮詢稿|科目|專業發展課程|文憑課程",
            re.I,
        ),
    ),
    (
        "student_activity",
        re.compile(
            r"交流|互訪|參觀|體驗|交換生|學習活動|"
            r"sister.?school|student.?activit|"
            r"姊妹學校(?!津貼)|全方位學習(?!.*津貼)",
            re.I,
        ),
    ),
    (
        "admin",
        re.compile(
            r"人事|校董|校監|法團校董會|投訴|紀律|危機管理|"
            r"administration|personnel|governance|appointment|聘任|"
            r"學校管理|校舍|設施|教師職位|學生人數預測|"
            r"學校行政|行政安排|行政措施",
            re.I,
        ),
    ),
]


def programme_for(
    *,
    source_id: str,
    circular_no: str | None = None,
) -> str:
    """Deterministic programme from source / circular number."""
    circ = (circular_no or "").strip().upper()
    if source_id in _CIRCULAR_SOURCES or circ.startswith("EDBC"):
        return "circular"
    mapped = _PROGRAMME_BY_SOURCE.get(source_id)
    if mapped:
        return mapped
    return "other"


def _abstract_from_extra(extra: dict | None) -> str:
    """Use circular 摘要 only — full row_text includes 學校類別 (often 津貼) and pollutes tags."""
    if not extra:
        return ""
    row = extra.get("row_text") or ""
    if not isinstance(row, str) or not row.strip():
        return ""
    cleaned = re.sub(r"\s+", " ", row)
    # Prefer the abstract segment between 摘要 and 學校類別
    m = re.search(r"摘要[：:]\s*(.+?)(?:\s*學校類別|$)", cleaned)
    if m:
        return m.group(1).strip()[:1500]
    # Drop school-type trailer if present
    cleaned = re.split(r"學校類別", cleaned, maxsplit=1)[0]
    return cleaned[:1500]


def topics_from_rules(text: str, *, source_id: str = "") -> list[str]:
    """Return matching topic ids from keyword rules (may be empty)."""
    blob = text or ""
    if source_id == "edb_lwlssg" and "grant_funding" not in blob:
        # LWLSSG corpus is primarily grant materials
        hits = ["grant_funding"]
    else:
        hits = []
    for topic, pattern in _TOPIC_RULES:
        if pattern.search(blob) and topic not in hits:
            hits.append(topic)
    if source_id == "sss_sister" and "student_activity" not in hits:
        hits.append("student_activity")
    return hits


def _normalize_topics(raw: list[str]) -> list[str]:
    out: list[str] = []
    for t in raw:
        key = (t or "").strip().lower().replace("-", "_").replace(" ", "_")
        if key in TOPICS and key not in out:
            out.append(key)
    if not out:
        return ["other"]
    # Drop redundant "other" when real topics exist
    if len(out) > 1 and "other" in out:
        out = [t for t in out if t != "other"]
    return out


async def topics_via_llm(title: str, abstract: str, source_id: str) -> list[str]:
    """Ask LLM to pick from closed topic vocab; returns normalized list."""
    allowed = ", ".join(sorted(TOPICS))
    prompt = (
        "You classify Hong Kong Education Bureau documents into topic tags.\n"
        f"Allowed topic ids ONLY: {allowed}\n"
        "Return a JSON array of 1–3 topic ids, nothing else.\n"
        f"source_id: {source_id}\n"
        f"title: {title[:500]}\n"
        f"abstract: {abstract[:1200]}\n"
    )
    try:
        llm = get_llm_client()
        with usage_scope("classify"):
            raw = await llm.chat(
                [
                    {
                        "role": "system",
                        "content": "You output only valid JSON arrays of topic id strings.",
                    },
                    {"role": "user", "content": prompt},
                ],
                stream=False,
            )
        if not isinstance(raw, str):
            # Some clients may return an async iterator even when stream=False
            parts: list[str] = []
            async for chunk in raw:  # type: ignore[union-attr]
                parts.append(str(chunk))
            text = "".join(parts).strip()
        else:
            text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "topics" in parsed:
            parsed = parsed["topics"]
        if not isinstance(parsed, list):
            return ["other"]
        return _normalize_topics([str(x) for x in parsed])
    except Exception:
        logger.exception("LLM topic classify failed for title=%s", title[:80])
        return ["other"]


async def classify_topics(
    *,
    title: str,
    abstract: str = "",
    source_id: str = "",
    use_llm: bool = True,
) -> list[str]:
    """Rules first; LLM when rules empty or only weak."""
    blob = f"{title}\n{abstract}"
    ruled = topics_from_rules(blob, source_id=source_id)
    if ruled and not (len(ruled) == 1 and ruled[0] == "other"):
        # Strong enough rule hit
        if use_llm and len(ruled) == 1 and len((title or "").strip()) < 4:
            # Tiny/generic titles (e.g. 簡報) — still ask LLM with abstract
            llm_topics = await topics_via_llm(title, abstract, source_id)
            merged = list(ruled)
            for t in llm_topics:
                if t not in merged and t != "other":
                    merged.append(t)
            return _normalize_topics(merged)
        return _normalize_topics(ruled)
    if use_llm:
        return await topics_via_llm(title, abstract, source_id)
    return ["other"]


def apply_programme(doc: Document) -> str:
    prog = programme_for(source_id=doc.source_id, circular_no=doc.circular_no)
    doc.programme = prog
    return prog


async def apply_classification(
    doc: Document,
    *,
    use_llm: bool = True,
    force_topics: bool = False,
) -> dict[str, Any]:
    """Set programme always; set topics if empty or force_topics."""
    prog = apply_programme(doc)
    existing = list(doc.topics or [])
    if existing and not force_topics:
        return {"programme": prog, "topics": existing, "topics_skipped": True}
    abstract = _abstract_from_extra(doc.extra if isinstance(doc.extra, dict) else None)
    topics = await classify_topics(
        title=doc.title or "",
        abstract=abstract,
        source_id=doc.source_id,
        use_llm=use_llm,
    )
    doc.topics = topics
    return {"programme": prog, "topics": topics, "topics_skipped": False}


async def ensure_classify_source(session: AsyncSession) -> None:
    src = await session.get(Source, CLASSIFY_SOURCE_ID)
    if src:
        return
    session.add(
        Source(
            id=CLASSIFY_SOURCE_ID,
            name_en="Classify documents",
            name_zh_hk="文件分類（計劃＋主題）",
            enabled=False,
            type="system",
            base_url="",
            config={},
        )
    )
    await session.commit()


async def backfill_classifications(
    session: AsyncSession,
    *,
    use_llm: bool = True,
    force_topics: bool = False,
    batch_size: int = 50,
) -> dict[str, Any]:
    """Scan all documents: set programme; classify topics when missing.

    Creates a CrawlRun so the status UI can poll live progress (like re-index).
    """
    await ensure_classify_source(session)

    running = await session.scalar(select(CrawlRun).where(CrawlRun.status == "running"))
    if running:
        return {
            "ok": False,
            "reason": "already_running",
            "run_id": str(running.id),
            "total": 0,
            "updated": 0,
            "topics_classified": 0,
            "use_llm": use_llm,
            "force_topics": force_topics,
        }

    rows = list((await session.scalars(select(Document).order_by(Document.created_at))).all())
    total = len(rows)

    run = CrawlRun(
        source_id=CLASSIFY_SOURCE_ID,
        status="running",
        discovered=total,
        downloaded=0,
        skipped=0,
        failed=0,
        progress_message=f"Classifying {total} documents…",
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    await emit_event(
        session,
        run_id=run.id,
        event_type="discovering",
        title=f"{total} documents to classify",
        source_id=CLASSIFY_SOURCE_ID,
    )

    updated = 0
    topics_set = 0
    skipped = 0
    failed = 0
    cancelled = False

    for i, doc in enumerate(rows, start=1):
        run = await session.get(CrawlRun, run.id)
        if run and run.cancel_requested:
            run.status = "cancelled"
            run.progress_message = "Cancelled by user"
            run.finished_at = datetime.now(timezone.utc)
            await emit_event(
                session,
                run_id=run.id,
                event_type="cancelled",
                source_id=CLASSIFY_SOURCE_ID,
            )
            await session.commit()
            cancelled = True
            break

        label = (doc.circular_no or doc.title or str(doc.id))[:120]
        await emit_event(
            session,
            run_id=run.id,
            event_type="classify_start",
            url=doc.file_url,
            title=label,
            source_id=doc.source_id,
        )

        try:
            result = await apply_classification(doc, use_llm=use_llm, force_topics=force_topics)
            updated += 1
            if result.get("topics_skipped"):
                skipped += 1
                await emit_event(
                    session,
                    run_id=run.id,
                    event_type="classify_skip",
                    url=doc.file_url,
                    title=label,
                    source_id=doc.source_id,
                )
            else:
                topics_set += 1
                await emit_event(
                    session,
                    run_id=run.id,
                    event_type="classify_ok",
                    url=doc.file_url,
                    title=label,
                    source_id=doc.source_id,
                )
        except Exception as exc:
            failed += 1
            logger.exception("classify failed for doc=%s", doc.id)
            await emit_event(
                session,
                run_id=run.id,
                event_type="classify_fail",
                url=doc.file_url,
                title=f"{label}: {exc}"[:200],
                source_id=doc.source_id,
            )

        if i % 2 == 0 or i == total or i % batch_size == 0:
            await _save_run_progress(
                session,
                run,
                discovered=total,
                downloaded=topics_set,
                skipped=skipped,
                failed=failed,
                message=(
                    f"Classified {topics_set}/{total} · "
                    f"Skipped {skipped} · Failed {failed}"
                ),
            )
            logger.info("classify backfill progress %s/%s", i, total)

    if not cancelled:
        run = await session.get(CrawlRun, run.id)
        if run:
            run.status = "completed"
            run.discovered = total
            run.downloaded = topics_set
            run.skipped = skipped
            run.failed = failed
            run.progress_message = (
                f"Done: classified {topics_set}, skipped {skipped}, failed {failed}"
            )
            run.finished_at = datetime.now(timezone.utc)
            await emit_event(
                session,
                run_id=run.id,
                event_type="done",
                title=(
                    f"Classified {topics_set} · Skipped {skipped} · Failed {failed}"
                ),
                source_id=CLASSIFY_SOURCE_ID,
            )
            await session.commit()

    return {
        "ok": True,
        "cancelled": cancelled,
        "run_id": str(run.id) if run else None,
        "total": total,
        "updated": updated,
        "topics_classified": topics_set,
        "skipped": skipped,
        "failed": failed,
        "use_llm": use_llm,
        "force_topics": force_topics,
    }
