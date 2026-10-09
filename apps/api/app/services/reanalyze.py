"""Re-analyze selected circulars: one school-action paragraph via the answer LLM.

Does not re-embed, reclassify, or change calendar activity dates.
Only the selected document body text is sent to the existing answer-model client.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.entities import Document, DocumentChunk
from app.services.ingest import extract_text_from_pdf, sanitize_text
from app.services.llm import get_llm_client
from app.services.runtime_settings import resolved_settings
from app.services.storage import get_object_bytes
from app.services.usage import usage_scope

SCHOOL_ACTION_KEY = "school_action"
UNVERIFIED_PREFIX = "未核對"
FAIL_KEEP_MESSAGE = "未能重新分析，原來結果保持不變"
MAX_BODY_CHARS = 24_000
LLM_TIMEOUT_SECONDS = 90.0

REANALYZE_SYSTEM = """你協助香港學校職員閱讀教育局通告。

任務：根據通告正文，只用一段文字說明「這份要學校做什麼」（行動、交回、申請、參加、注意事項）。
規則：
1. 只根據正文；正文沒有的不要臆造。
2. 輸出一段完整文字，不要條列、不要標題、不要 markdown。
3. 用通告原文語言；中文用繁體（香港）。
4. 不要重複整份通告；聚焦學校要做的事。
5. 不要自行加上「未核對」字樣（系統會標示）。
"""


def answer_model_configured() -> bool:
    """True when the Q&A answer-model provider has the credentials/model it needs."""
    rs = resolved_settings()
    if rs.get("llm_provider") == "ollama":
        return bool(str(rs.get("ollama_model") or "").strip())
    return bool(str(rs.get("openrouter_api_key") or "").strip())


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
    clipped = body.strip()
    if len(clipped) > MAX_BODY_CHARS:
        clipped = clipped[:MAX_BODY_CHARS].rstrip() + "…"
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
    """Re-analyze one document. On failure, keep the previous school_action."""
    doc = await db.get(Document, document_id)
    if doc is None:
        return {
            "document_id": str(document_id),
            "ok": False,
            "school_action": None,
            "error": "not_found",
            "message": FAIL_KEEP_MESSAGE,
        }

    previous = school_action_from_extra(doc.extra)
    base = {
        "document_id": str(doc.id),
        "school_action": previous,
        "message": FAIL_KEEP_MESSAGE,
    }

    if not answer_model_configured():
        return {**base, "ok": False, "error": "model_unset"}

    body = await load_document_body(db, doc)
    if not body.strip():
        return {**base, "ok": False, "error": "no_text"}

    try:
        raw = await asyncio.wait_for(_call_answer_model(body), timeout=LLM_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return {**base, "ok": False, "error": "timeout"}
    except Exception:
        return {**base, "ok": False, "error": "error"}

    if not raw or _is_demo_answer(raw):
        error = "model_unset" if _is_demo_answer(raw) else "empty"
        return {**base, "ok": False, "error": error}

    stored = with_unverified_prefix(raw)
    extra = dict(doc.extra or {})
    extra[SCHOOL_ACTION_KEY] = stored
    doc.extra = extra
    # JSONB in-place mutation needs an explicit dirty flag on real ORM instances.
    if hasattr(doc, "_sa_instance_state"):
        flag_modified(doc, "extra")
    await db.flush()

    return {
        "document_id": str(doc.id),
        "ok": True,
        "school_action": stored,
        "error": None,
        "message": None,
    }


async def reanalyze_documents(db: AsyncSession, document_ids: list[uuid.UUID]) -> list[dict[str, Any]]:
    """Re-analyze only the given ids, in order. Never touches unselected documents."""
    results: list[dict[str, Any]] = []
    for doc_id in document_ids:
        results.append(await reanalyze_one(db, doc_id))
    return results
