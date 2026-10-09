"""Re-analyze selected circulars: school-action paragraph + activity dates via LLM.

Activity dates prefer the answer-model LLM (JSON). Falls back to the local
regex collector when the LLM response is unusable. Does not re-embed or reclassify.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.collectors.activity_dates import apply_document_activities
from app.models.entities import Document, DocumentChunk
from app.services.ingest import extract_text_from_pdf, sanitize_text
from app.services.llm import get_llm_client
from app.services.runtime_settings import resolved_settings
from app.services.storage import get_object_bytes
from app.services.usage import usage_scope

logger = logging.getLogger(__name__)

SCHOOL_ACTION_KEY = "school_action"
UNVERIFIED_PREFIX = "未核對"
FAIL_KEEP_MESSAGE = "未能重新分析，原來結果保持不變"
MAX_BODY_CHARS = 24_000
LLM_TIMEOUT_SECONDS = 90.0
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)

REANALYZE_SYSTEM = """你協助香港學校職員閱讀教育局通告。

任務：根據通告正文，只用一段文字說明「這份要學校做什麼」（行動、交回、申請、參加、注意事項）。
規則：
1. 只根據正文；正文沒有的不要臆造。
2. 輸出一段完整文字，不要條列、不要標題、不要 markdown。
3. 用通告原文語言；中文用繁體（香港）。
4. 不要重複整份通告；聚焦學校要做的事。
5. 不要自行加上「未核對」字樣（系統會標示）。
"""

ACTIVITIES_SYSTEM = """你協助香港學校職員從教育局通告抽出「活動／限期」資料，供月曆使用。

任務：輸出一個 JSON 陣列（不要其他說明、不要 markdown 標題）。每個元素為物件，欄位：
- name: 活動或事項名稱（字串或 null）
- starts_at: 開始日期 yyyy-mm-dd（字串或 null）
- deadline_at: 截止日期／完結日期 yyyy-mm-dd（字串或 null）
- summary: 一句簡述（字串或 null）
- location: 地點（字串或 null）

規則：
1. 只根據正文；沒有寫明的日期不要臆造。
2. 日期必須是 yyyy-mm-dd；無法確定則該欄為 null。
3. 納入：活動日期、報名／交回／回覆／申請限期、講座／培訓／比賽等。
4. 排除：通告發出／修訂日期、學年（如 2025/26）、生效日期、取代舊通告的背景日期、局方信頭地址。
5. 同一事項若有開始與截止，合併為一筆。
6. 正文沒有可上曆的活動時輸出 []。
7. 中文用繁體（香港）；只輸出 JSON 陣列。
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


def _normalize_iso_date(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a"}:
        return None
    if not _ISO_DATE.fullmatch(text):
        return None
    try:
        date.fromisoformat(text)
    except ValueError:
        return None
    return text


def _optional_str(value: object, *, max_len: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none"}:
        return None
    return text[:max_len]


def _normalize_activity_item(item: object) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    starts_at = _normalize_iso_date(item.get("starts_at"))
    deadline_at = _normalize_iso_date(item.get("deadline_at"))
    name = _optional_str(item.get("name"), max_len=200)
    summary = _optional_str(item.get("summary"), max_len=500)
    location = _optional_str(item.get("location"), max_len=200)
    if not starts_at and not deadline_at:
        return None
    return {
        "name": name,
        "starts_at": starts_at,
        "deadline_at": deadline_at,
        "summary": summary,
        "location": location,
    }


def parse_llm_activities(text: str) -> list[dict[str, Any]]:
    """Parse LLM JSON array into stored activity dicts. Raises ValueError if unusable."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty activities response")
    fence = _JSON_FENCE.search(raw)
    if fence:
        raw = fence.group(1).strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end < start:
        raise ValueError("LLM did not return a JSON array")
    parsed = json.loads(raw[start : end + 1])
    if not isinstance(parsed, list):
        raise ValueError("LLM did not return a JSON array")
    out: list[dict[str, Any]] = []
    for item in parsed:
        normalized = _normalize_activity_item(item)
        if normalized is not None:
            out.append(normalized)
    return out


def refresh_document_activities(doc: object, body: str) -> bool:
    """Re-extract activities from body text via local regex. Returns True if changed."""
    if not (body or "").strip():
        return False
    changed = apply_document_activities(doc, body)
    if changed:
        _flag_json_if_orm(doc, "activities")
    return changed


def apply_llm_activities(doc: object, activities: list[dict[str, Any]]) -> bool:
    """Replace document.activities with LLM result. Returns True if changed."""
    current = getattr(doc, "activities", None) or []
    if current == activities:
        return False
    setattr(doc, "activities", activities)
    _flag_json_if_orm(doc, "activities")
    return True


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


async def _call_activities_model(body: str) -> str:
    clipped = _clip_body(body)
    llm = get_llm_client()
    with usage_scope("reanalyze"):
        answer = await llm.chat(
            [
                {"role": "system", "content": ACTIVITIES_SYSTEM},
                {"role": "user", "content": clipped},
            ],
            stream=False,
            reasoning=False,
            apply_top_p=True,
        )
    if not isinstance(answer, str):
        return ""
    return answer.strip()


async def refresh_activities_prefer_llm(doc: object, body: str) -> bool:
    """Prefer LLM activity extraction; fall back to local regex on failure."""
    if not (body or "").strip():
        return False
    try:
        raw = await asyncio.wait_for(_call_activities_model(body), timeout=LLM_TIMEOUT_SECONDS)
        if raw and not _is_demo_answer(raw):
            activities = parse_llm_activities(raw)
            return apply_llm_activities(doc, activities)
    except Exception:
        pass
    return refresh_document_activities(doc, body)


async def reanalyze_one(db: AsyncSession, document_id: uuid.UUID) -> dict[str, Any]:
    """Re-analyze one document. On school-action LLM failure, keep the previous text.

    When body text is available, refresh activities via LLM (regex fallback).
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
    if body.strip() and answer_model_configured():
        activities_changed = await refresh_activities_prefer_llm(doc, body)
    elif body.strip():
        activities_changed = refresh_document_activities(doc, body)

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


def auto_ai_analyze_enabled() -> bool:
    """True when indexing should ask the LLM for school actions and activity dates."""
    return bool(resolved_settings().get("auto_ai_analyze"))


async def maybe_auto_ai_analyze(
    db: AsyncSession,
    document_id: uuid.UUID,
    *,
    has_text: bool,
) -> bool:
    """Run school-action and activity-date analysis after a document is indexed.

    Returns True when analysis was attempted. Failures stay inside this call so
    indexing can still finish with the local date rules already stored.
    """
    if not has_text or not auto_ai_analyze_enabled():
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
