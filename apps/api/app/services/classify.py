"""Document programme + topic classification (rules first, LLM fallback)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Document
from app.services.llm import get_llm_client

logger = logging.getLogger(__name__)

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
        assert isinstance(raw, str)
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


async def backfill_classifications(
    session: AsyncSession,
    *,
    use_llm: bool = True,
    force_topics: bool = False,
    batch_size: int = 50,
) -> dict[str, Any]:
    """Scan all documents: set programme; classify topics when missing."""
    rows = list((await session.scalars(select(Document).order_by(Document.created_at))).all())
    updated = 0
    topics_set = 0
    for i, doc in enumerate(rows):
        before_topics = list(doc.topics or [])
        result = await apply_classification(doc, use_llm=use_llm, force_topics=force_topics)
        updated += 1
        if not result.get("topics_skipped"):
            topics_set += 1
        if (i + 1) % batch_size == 0:
            await session.commit()
            logger.info("classify backfill progress %s/%s", i + 1, len(rows))
        # Avoid rewriting identical programme-only updates flooding logs
        _ = before_topics
    await session.commit()
    return {
        "total": len(rows),
        "updated": updated,
        "topics_classified": topics_set,
        "use_llm": use_llm,
        "force_topics": force_topics,
    }
