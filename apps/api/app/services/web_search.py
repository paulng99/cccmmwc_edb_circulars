"""Public web search used only when the local circular library has no match."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from app.services.runtime_settings import resolved_settings
from app.services.usage import parse_jina_reader_usage, record_usage, usage_scope

logger = logging.getLogger(__name__)

MAX_WEB_RESULTS = 5
MAX_SNIPPET_CHARS = 800
SEARCH_TIMEOUT_SECONDS = 25


@dataclass(frozen=True)
class WebSearchOutcome:
    results: list[dict[str, str]]
    """True when a search request was actually sent (a key was configured)."""
    attempted: bool


def _clip(text: str, limit: int) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "…"


def _as_result_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        nested = data.get("results") or data.get("items")
        if isinstance(nested, list):
            return nested
        if data.get("url") or data.get("title"):
            return [data]
    for key in ("results", "items"):
        nested = payload.get(key)
        if isinstance(nested, list):
            return nested
    return []


def parse_search_results(payload: Any, *, limit: int = MAX_WEB_RESULTS) -> list[dict[str, str]]:
    """Normalise a Jina Search JSON body into title / url / snippet rows."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return []
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in _as_result_list(payload):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("link") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        if url in seen:
            continue
        title = _clip(str(item.get("title") or item.get("name") or url), 180)
        snippet = _clip(
            str(item.get("description") or item.get("snippet") or item.get("content") or ""),
            MAX_SNIPPET_CHARS,
        )
        if not snippet:
            snippet = "(No snippet returned.)"
        seen.add(url)
        rows.append({"title": title or url, "url": url, "content": snippet})
        if len(rows) >= limit:
            break
    return rows


async def search_web(query: str, *, limit: int = MAX_WEB_RESULTS) -> WebSearchOutcome:
    """Search the public web. Never raises; an empty outcome means chat can continue."""
    text = " ".join((query or "").split())
    if not text:
        return WebSearchOutcome(results=[], attempted=False)
    rs = resolved_settings()
    api_key = str(rs.get("jina_api_key") or "").strip()
    if not api_key:
        logger.info("web search skipped: jina api key is not configured")
        return WebSearchOutcome(results=[], attempted=False)

    url = "https://s.jina.ai/" + quote(text[:300], safe="")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "X-Respond-With": "no-content",
    }
    try:
        async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT_SECONDS) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            body = resp.text
            header_map = getattr(resp, "headers", {})
        try:
            with usage_scope("web_search"):
                await record_usage(parse_jina_reader_usage(body, header_map))
        except Exception:
            logger.warning("web search usage record failed", exc_info=True)
        return WebSearchOutcome(results=parse_search_results(body, limit=limit), attempted=True)
    except Exception:
        logger.warning("web search failed", exc_info=True)
        return WebSearchOutcome(results=[], attempted=True)
