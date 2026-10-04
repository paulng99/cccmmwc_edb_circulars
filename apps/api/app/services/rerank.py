"""Jina reranker for post-retrieval candidate ordering."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.runtime_settings import resolved_settings
from app.services.usage import parse_jina_embed_usage, record_usage, usage_scope

logger = logging.getLogger(__name__)

DEFAULT_RERANKER_MODEL = "jina-reranker-v2-base-multilingual"
RERANK_TIMEOUT_SECONDS = 30.0
MAX_DOC_CHARS = 1200


def _hit_document_text(hit: dict[str, Any]) -> str:
    title = (hit.get("title") or "").strip()
    circ = (hit.get("circular_no") or "").strip()
    content = (hit.get("content") or "").strip()
    head = " | ".join(p for p in (title, circ) if p)
    body = f"{head}\n{content}".strip() if head else content
    return body[:MAX_DOC_CHARS]


async def rerank_hits(
    query: str,
    hits: list[dict[str, Any]],
    *,
    top_n: int,
) -> list[dict[str, Any]]:
    """Rerank hits with Jina; return original order on missing key / failure / empty."""
    if not hits or top_n <= 0:
        return []
    q = (query or "").strip()
    if not q:
        return hits[:top_n]

    rs = resolved_settings()
    api_key = (rs.get("jina_api_key") or "").strip()
    if not api_key:
        return hits[:top_n]

    model = str(rs.get("jina_reranker_model") or DEFAULT_RERANKER_MODEL)
    documents = [_hit_document_text(h) for h in hits]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "query": q,
        "documents": documents,
        "top_n": min(top_n, len(documents)),
        "return_documents": False,
    }
    try:
        with usage_scope("rerank"):
            async with httpx.AsyncClient(timeout=RERANK_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    "https://api.jina.ai/v1/rerank",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
            await record_usage(parse_jina_embed_usage(data, model=model))
    except Exception:
        logger.exception("Jina rerank failed; keeping retrieval order")
        return hits[:top_n]

    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list) or not results:
        return hits[:top_n]

    ordered: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in results:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item["index"])
        except (KeyError, TypeError, ValueError):
            continue
        if idx < 0 or idx >= len(hits) or idx in seen:
            continue
        seen.add(idx)
        hit = dict(hits[idx])
        score = item.get("relevance_score", item.get("score"))
        if score is not None:
            try:
                hit["score"] = float(score)
            except (TypeError, ValueError):
                pass
        hit["match"] = "rerank"
        ordered.append(hit)
        if len(ordered) >= top_n:
            break

    if not ordered:
        return hits[:top_n]
    # Backfill if API returned fewer than top_n
    if len(ordered) < top_n:
        for i, hit in enumerate(hits):
            if i in seen:
                continue
            ordered.append(hit)
            if len(ordered) >= top_n:
                break
    return ordered[:top_n]
