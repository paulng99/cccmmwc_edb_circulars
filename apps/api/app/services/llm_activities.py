"""LLM extraction of calendar start/deadline activities from circular body text.

Local regex results must not be used for display or backfill. On LLM failure,
callers omit dates (empty activities) rather than falling back to regex.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from app.services.llm import get_llm_client
from app.services.runtime_settings import resolved_settings
from app.services.usage import usage_scope

logger = logging.getLogger(__name__)

ACTIVITIES_PARSED_FLAG = "llm-1"
BACKFILL_STATUS_KEY = "activities_llm_backfill"
BACKFILL_STATUS_IN_PROGRESS = "in_progress"
BACKFILL_STATUS_DONE = "done"
BACKFILL_DONE_KEY = "activities_llm_backfill_done"
BACKFILL_TOTAL_KEY = "activities_llm_backfill_total"
BACKFILL_CURRENT_KEY = "activities_llm_backfill_current"
BACKFILL_PAUSED_KEY = "activities_llm_backfill_paused"

MAX_BODY_CHARS = 24_000
LLM_TIMEOUT_SECONDS = 90.0
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)

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
4. 排除：通告發出／修訂／更新日期、學年（如 2025/26）、生效日期、取代舊通告的背景日期、局方信頭／署名地址。
5. 同一事項若有開始與截止，合併為一筆；不同事項必須分開多筆，不要合併無關項目。
6. 正文沒有可上曆的活動時輸出 []。
7. 中文用繁體（香港）；只輸出 JSON 陣列。
"""


def answer_model_configured() -> bool:
    """True when the Q&A answer-model provider has the credentials/model it needs."""
    rs = resolved_settings()
    if rs.get("llm_provider") == "ollama":
        return bool(str(rs.get("ollama_model") or "").strip())
    return bool(str(rs.get("openrouter_api_key") or "").strip())


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


def _is_demo_answer(text: str) -> bool:
    return text.lstrip().startswith("[Demo mode:")


def _flag_json_if_orm(doc: object, field: str) -> None:
    if hasattr(doc, "_sa_instance_state"):
        flag_modified(doc, field)


def mark_activities_parsed(doc: object) -> None:
    extra = dict(getattr(doc, "extra", None) or {})
    extra["activities_parsed"] = ACTIVITIES_PARSED_FLAG
    setattr(doc, "extra", extra)
    _flag_json_if_orm(doc, "extra")


def apply_llm_activities(doc: object, activities: list[dict[str, Any]]) -> bool:
    """Replace document.activities with LLM result and mark parsed. Returns True if changed."""
    current = getattr(doc, "activities", None) or []
    activities_changed = current != activities
    if activities_changed:
        setattr(doc, "activities", activities)
        _flag_json_if_orm(doc, "activities")
    mark_activities_parsed(doc)
    return activities_changed


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


async def extract_activities_via_llm(body: str) -> list[dict[str, Any]] | None:
    """Return parsed activities, or None when the LLM path is unusable (no regex fallback)."""
    if not (body or "").strip():
        return None
    if not answer_model_configured():
        return None
    try:
        raw = await asyncio.wait_for(_call_activities_model(body), timeout=LLM_TIMEOUT_SECONDS)
        if not raw or _is_demo_answer(raw):
            return None
        return parse_llm_activities(raw)
    except Exception:
        logger.exception("LLM activity extraction failed")
        return None


async def refresh_activities_llm_only(doc: object, body: str) -> bool:
    """Set activities from LLM only. On failure, clear activities (never use local regex)."""
    if not (body or "").strip():
        # No body — clear dates and mark parsed so backfill does not loop.
        return apply_llm_activities(doc, [])
    activities = await extract_activities_via_llm(body)
    if activities is None:
        return apply_llm_activities(doc, [])
    return apply_llm_activities(doc, activities)
