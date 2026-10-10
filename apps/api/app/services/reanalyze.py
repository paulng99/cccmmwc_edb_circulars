"""Re-analyze selected circulars: school-action paragraph + activity dates via LLM.

Activity dates use the answer-model LLM only. Local regex is voided for display —
on LLM failure, activities are cleared (not filled from regex). Does not re-embed
or reclassify.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.collectors.registry import load_sources_config
from app.models.entities import Document, DocumentChunk
from app.services.ingest import extract_text_from_pdf, sanitize_text
from app.services.llm import get_llm_client
from app.services.llm_activities import (
    ACTIVITIES_PARSED_FLAG,
    answer_model_configured,
    apply_llm_activities,
    parse_llm_activities,
    refresh_activities_llm_only,
)
from app.services.storage import get_object_bytes
from app.services.usage import usage_scope

logger = logging.getLogger(__name__)

SCHOOL_ACTION_KEY = "school_action"
UNVERIFIED_PREFIX = "未核對"
FAIL_KEEP_MESSAGE = "未能重新分析，原來結果保持不變"
MAX_BODY_CHARS = 24_000
LLM_TIMEOUT_SECONDS = 90.0

# Re-export for existing tests/imports.
__all__ = [
    "ACTIVITIES_PARSED_FLAG",
    "FAIL_KEEP_MESSAGE",
    "SCHOOL_ACTION_KEY",
    "UNVERIFIED_PREFIX",
    "activities_payload",
    "answer_model_configured",
    "apply_llm_activities",
    "load_document_body",
    "maybe_auto_ai_analyze",
    "parse_llm_activities",
    "reanalyze_documents",
    "reanalyze_one",
    "refresh_activities_llm_only",
    "school_action_from_extra",
    "source_auto_ai_enabled",
    "with_unverified_prefix",
]

REANALYZE_SYSTEM = """你協助香港學校職員閱讀教育局通告。

任務：根據通告正文，只用一段文字說明「這份要學校做什麼」（行動、交回、申請、參加、注意事項）。
規則：
1. 只根據正文；正文沒有的不要臆造。
2. 輸出一段完整文字，不要條列、不要標題、不要 markdown。
3. 用通告原文語言；中文用繁體（香港）。
4. 不要重複整份通告；聚焦學校要做的事。
5. 不要自行加上「未核對」字樣（系統會標示）。
"""


def school_action_from_extra(extra: object) -> str | None:
    if not isinstance(extra, dict):
        return None
    raw = extra.get(SCHOOL_ACTION_KEY)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def with_unverified_prefix(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith(UNVERIFIED_PREFIX):
        return cleaned
    return f"{UNVERIFIED_PREFIX}\n{cleaned}"


def activities_payload(doc: object) -> list[dict[str, Any]]:
    raw = getattr(doc, "activities", None) or []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _flag_json_if_orm(doc: object, field: str) -> None:
    if hasattr(doc, "_sa_instance_state"):
        flag_modified(doc, field)


def _clip_body(body: str) -> str:
    clipped = body.strip()
    if len(clipped) > MAX_BODY_CHARS:
        return clipped[:MAX_BODY_CHARS].rstrip() + "…"
    return clipped


def _is_demo_answer(text: str) -> bool:
    return text.lstrip().startswith("[Demo mode:")


async def load_document_body(db: AsyncSession, doc: Document) -> str:
    """Prefer indexed chunks (no re-embed). Fall back to PDF text extract."""
    result = await db.execute(
        select(DocumentChunk.content)
        .where(DocumentChunk.document_id == doc.id)
        .order_by(DocumentChunk.chunk_index.asc())
    )
    parts = [str(row[0]).strip() for row in result.all() if row[0] and str(row[0]).strip()]
    if parts:
        return sanitize_text("\n\n".join(parts))

    if not doc.storage_key:
        return ""
    try:
        raw = get_object_bytes(doc.storage_key)
    except Exception:
        return ""
    return sanitize_text(extract_text_from_pdf(raw))


async def _call_answer_model(body: str) -> str:
    clipped = _clip_body(body)
    llm = get_llm_client()
    with usage_scope("reanalyze"):
        answer = await llm.chat(
            [
                {"role": "system", "content": REANALYZE_SYSTEM},
                {"role": "user", "content": clipped},
            ],
            stream=False,
            reasoning=False,
            apply_top_p=True,
        )
    if not isinstance(answer, str):
        return ""
    return answer.strip()


async def reanalyze_one(db: AsyncSession, document_id: uuid.UUID) -> dict[str, Any]:
    """Re-analyze one document. On school-action LLM failure, keep the previous text.

    When body text is available, refresh activities via LLM only (no regex fallback).
    """
    doc = await db.get(Document, document_id)
    if doc is None:
        return {
            "document_id": str(document_id),
            "ok": False,
            "school_action": None,
            "activities": [],
            "error": "not_found",
            "message": FAIL_KEEP_MESSAGE,
        }

    previous = school_action_from_extra(doc.extra)
    body = await load_document_body(db, doc)
    activities_changed = False
    if body.strip():
        activities_changed = await refresh_activities_llm_only(doc, body)

    async def _fail(error: str) -> dict[str, Any]:
        if activities_changed:
            await db.flush()
        return {
            "document_id": str(doc.id),
            "ok": False,
            "school_action": previous,
            "activities": activities_payload(doc),
            "error": error,
            "message": FAIL_KEEP_MESSAGE,
        }

    if not answer_model_configured():
        return await _fail("model_unset")

    if not body.strip():
        return await _fail("no_text")

    try:
        raw = await asyncio.wait_for(_call_answer_model(body), timeout=LLM_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return await _fail("timeout")
    except Exception:
        return await _fail("error")

    if not raw or _is_demo_answer(raw):
        error = "model_unset" if _is_demo_answer(raw) else "empty"
        return await _fail(error)

    stored = with_unverified_prefix(raw)
    extra = dict(doc.extra or {})
    extra[SCHOOL_ACTION_KEY] = stored
    doc.extra = extra
    # JSONB in-place mutation needs an explicit dirty flag on real ORM instances.
    _flag_json_if_orm(doc, "extra")
    await db.flush()

    return {
        "document_id": str(doc.id),
        "ok": True,
        "school_action": stored,
        "activities": activities_payload(doc),
        "error": None,
        "message": None,
    }


def source_auto_ai_enabled(source_id: str | None) -> bool:
    """True when this knowledge source asks indexing to use the LLM for school actions."""
    if not source_id:
        return False
    try:
        sources = load_sources_config()
    except Exception:
        logger.exception("Could not read sources while checking auto AI analysis")
        return False
    for src in sources:
        if isinstance(src, dict) and src.get("id") == source_id:
            return src.get("auto_ai_analyze") is True
    return False


async def maybe_auto_ai_analyze(
    db: AsyncSession,
    document_id: uuid.UUID,
    *,
    has_text: bool,
    enabled: bool,
) -> bool:
    """Run school-action analysis after a document is indexed (when source enables it).

    Activity dates are handled separately on ingest via LLM-only extraction.
    Failures stay inside this call so indexing can still finish.
    """
    if not has_text or not enabled:
        return False
    try:
        # Savepoint: a failed analysis must not abort the index transaction.
        async with db.begin_nested():
            await reanalyze_one(db, document_id)
    except Exception:
        logger.exception("Auto AI analysis failed for %s", document_id)
    return True


async def reanalyze_documents(db: AsyncSession, document_ids: list[uuid.UUID]) -> list[dict[str, Any]]:
    """Re-analyze only the given ids, in order. Never touches unselected documents."""
    results: list[dict[str, Any]] = []
    for doc_id in document_ids:
        results.append(await reanalyze_one(db, doc_id))
    return results
