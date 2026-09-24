from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

from app.services.sources_config import SourceConfigError, normalize_base_url, validate_source

SearchFn = Callable[[str], Awaitable[str]]
CompleteFn = Callable[[str], Awaitable[str]]


def build_search_query(mode: str, query: str) -> str:
    text = query.strip()
    if mode == "topic":
        if not text:
            raise ValueError("query is required")
        return f"{text} site:edb.gov.hk OR site:edcity.hk"
    if mode == "url":
        parsed = urlparse(text)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("url must be http(s)")
        return text
    raise ValueError("mode must be topic or url")


def parse_llm_sources(text: str) -> list:
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end < start:
        raise ValueError("LLM did not return a JSON array")
    parsed = json.loads(raw[start : end + 1])
    if not isinstance(parsed, list):
        raise ValueError("LLM did not return a JSON array")
    return parsed[:5]


def filter_drafts(drafts: list, existing: list[dict]) -> tuple[list[dict], int]:
    known_ids = {str(s.get("id")) for s in existing}
    known_urls = set()
    for src in existing:
        url = src.get("base_url")
        if isinstance(url, str) and url.strip():
            known_urls.add(normalize_base_url(url))
    kept: list[dict] = []
    dropped = 0
    for draft in drafts:
        if not isinstance(draft, dict):
            dropped += 1
            continue
        try:
            cleaned = validate_source({**draft, "enabled": False})
        except SourceConfigError:
            dropped += 1
            continue
        if cleaned["id"] in known_ids or normalize_base_url(cleaned["base_url"]) in known_urls:
            dropped += 1
            continue
        known_ids.add(cleaned["id"])
        known_urls.add(normalize_base_url(cleaned["base_url"]))
        kept.append(cleaned)
    return kept, dropped


async def suggest_sources(
    *,
    mode: str,
    query: str,
    existing: list[dict],
    jina_api_key: str,
    search: SearchFn,
    complete: CompleteFn,
) -> dict:
    if not jina_api_key:
        raise SourceConfigError("jina_not_configured")
    search_query = build_search_query(mode, query)
    evidence = await search(search_query)
    prompt = (
        "Turn the search evidence into 1 to 5 crawl source objects as a JSON array only.\n"
        "Allowed type: site_attachments or circular_aspnet.\n"
        "site_attachments needs allow_hosts and file_extensions from "
        ".pdf .doc .docx .xls .xlsx .ppt .pptx.\n"
        "circular_aspnet needs langs [1 and/or 2] and year_from <= year_to.\n"
        "id must match ^[a-z][a-z0-9_]{1,62}$. Include name.en and name.zh-HK.\n"
        "Set enabled to false, priority 0-9, rate_limit_seconds 1.5, "
        "schedule a 5-field cron.\n"
        f"Evidence:\n{evidence[:8000]}"
    )
    raw = await complete(prompt)
    drafts = parse_llm_sources(raw)
    suggestions, dropped = filter_drafts(drafts, existing)
    return {"suggestions": suggestions, "dropped": dropped}
