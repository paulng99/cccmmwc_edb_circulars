"""Structured LLM rewrite for retrieval-only query expansion."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.llm import get_llm_client
from app.services.usage import usage_scope

logger = logging.getLogger(__name__)

REWRITE_TIMEOUT_SECONDS = 8.0
MAX_SEARCH_QUERY_CHARS = 200
MAX_SEARCH_QUERIES = 2

REWRITE_SYSTEM = """You are a retrieval assistant for Hong Kong Education Bureau (EDB) circulars and school grants.

Rules:
1. Do NOT answer the user's question. Output retrieval strings only.
2. Output a single JSON object — no markdown fences, no commentary.
3. Prefer official EDB Traditional Chinese programme names when recognizable.
4. Include common English acronyms and Traditional Chinese variants when relevant.
5. Do not invent circular numbers or programme names you are unsure about.
6. search_queries must be search-oriented keyword strings (not full answers), ≤200 chars each.

Known programme aliases (use when the question matches):
- LWLSSG / 全方位學習津貼 / 姊妹學校津貼 → 全方位學習及姊妹學校津貼
- 校本課後 / AEG → 校本課後學習及支援計劃
- 優化校本 → 優化校本學習活動支援津貼

JSON schema:
{
  "programme_names": ["..."],
  "circular_nos": ["EDBC…/YYYY"],
  "school_years": ["YYYY/YY"],
  "synonyms": ["..."],
  "search_queries": ["primary search string", "optional alternate"]
}
"""


@dataclass
class RewriteResult:
    programme_names: list[str] = field(default_factory=list)
    circular_nos: list[str] = field(default_factory=list)
    school_years: list[str] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    used_llm: bool = False


def _strip_fences(text: str) -> str:
    raw = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if fence:
        return fence.group(1).strip()
    return raw


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            s = item.strip()
            if s and s not in out:
                out.append(s)
    return out


def _clip_query(text: str) -> str:
    return (text or "").strip()[:MAX_SEARCH_QUERY_CHARS].strip()


def parse_rewrite_payload(text: str) -> RewriteResult:
    """Parse LLM JSON into RewriteResult. Raises ValueError on invalid payload."""
    raw = _strip_fences(text)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("rewrite_not_json_object")
    parsed = json.loads(raw[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("rewrite_not_object")

    programme_names = _as_str_list(parsed.get("programme_names"))
    circular_nos = _as_str_list(parsed.get("circular_nos"))
    school_years = _as_str_list(parsed.get("school_years"))
    synonyms = _as_str_list(parsed.get("synonyms"))

    search_queries = [_clip_query(q) for q in _as_str_list(parsed.get("search_queries"))]
    search_queries = [q for q in search_queries if q]

    # Compat: single search_query field
    if not search_queries:
        single = parsed.get("search_query")
        if isinstance(single, str) and single.strip():
            search_queries = [_clip_query(single)]

    if not search_queries:
        parts = programme_names + circular_nos + school_years + synonyms
        composed = _clip_query(" ".join(parts))
        if composed:
            search_queries = [composed]

    if not search_queries:
        raise ValueError("rewrite_empty_queries")

    return RewriteResult(
        programme_names=programme_names,
        circular_nos=circular_nos,
        school_years=school_years,
        synonyms=synonyms,
        search_queries=search_queries[:MAX_SEARCH_QUERIES],
        used_llm=True,
    )


def build_dual_queries(original: str, rewritten: RewriteResult | None) -> list[str]:
    """Pick up to two distinct retrieval queries: primary rewrite + alternate/original."""
    base = (original or "").strip()
    if not base:
        return []
    if rewritten is None or not rewritten.search_queries:
        return [base]

    primary = rewritten.search_queries[0]
    queries: list[str] = []
    for candidate in (primary, *rewritten.search_queries[1:], base):
        c = (candidate or "").strip()
        if not c:
            continue
        if c not in queries:
            queries.append(c)
        if len(queries) >= MAX_SEARCH_QUERIES:
            break
    return queries or [base]


def hit_key(hit: dict[str, Any]) -> str:
    return f"{hit.get('document_id')}:{hit.get('chunk_index')}"


def merge_multi_query_hits(
    hit_lists: list[list[dict[str, Any]]],
    *,
    top_k: int,
    both_boost: float = 0.12,
) -> list[dict[str, Any]]:
    """Merge retrieval lists by document_id:chunk_index; max score + boost if in both."""
    if top_k <= 0:
        return []
    by_key: dict[str, dict[str, Any]] = {}
    seen_in: dict[str, set[int]] = {}
    for list_idx, hits in enumerate(hit_lists):
        for hit in hits:
            key = hit_key(hit)
            seen_in.setdefault(key, set()).add(list_idx)
            score = float(hit.get("score") or 0.0)
            if key not in by_key:
                by_key[key] = dict(hit)
                continue
            existing = by_key[key]
            if score > float(existing.get("score") or 0.0):
                merged = dict(hit)
                merged["match"] = existing.get("match") or hit.get("match")
                by_key[key] = merged
                existing = merged
            # Keep highest score so far (max); boost applied after loop.
            existing["score"] = max(float(existing.get("score") or 0.0), score)

    for key, hit in by_key.items():
        if len(seen_in.get(key, ())) >= 2:
            hit["score"] = min(1.0, float(hit.get("score") or 0.0) + both_boost)
            if hit.get("match") != "hybrid":
                hit["match"] = "multi_query"

    merged = sorted(by_key.values(), key=lambda h: float(h.get("score") or 0.0), reverse=True)
    return merged[:top_k]


def filter_hits_by_min_score(
    hits: list[dict[str, Any]],
    min_score: float,
) -> list[dict[str, Any]]:
    """Drop hits below min_score. min_score <= 0 keeps all (disabled)."""
    try:
        threshold = float(min_score)
    except (TypeError, ValueError):
        return list(hits)
    if threshold <= 0:
        return list(hits)
    return [h for h in hits if float(h.get("score") or 0.0) >= threshold]


async def rewrite_retrieve_query(question: str) -> RewriteResult | None:
    """Call LLM to expand a retrieve query. Returns None on timeout/parse/LLM failure."""
    q = (question or "").strip()
    if not q:
        return None
    llm = get_llm_client()
    messages = [
        {"role": "system", "content": REWRITE_SYSTEM},
        {"role": "user", "content": q},
    ]
    try:
        with usage_scope("retrieve_rewrite"):
            raw = await asyncio.wait_for(
                llm.chat(messages, stream=False, reasoning=False),
                timeout=REWRITE_TIMEOUT_SECONDS,
            )
        if not isinstance(raw, str):
            parts: list[str] = []
            async for chunk in raw:  # type: ignore[union-attr]
                parts.append(str(chunk))
            text = "".join(parts)
        else:
            text = raw
        return parse_rewrite_payload(text)
    except Exception:
        logger.exception("retrieve query rewrite failed; falling back to original")
        return None
