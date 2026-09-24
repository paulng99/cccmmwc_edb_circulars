from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import SourceSuggestBody, SourcesConfigBody
from app.core.config import get_settings
from app.core.db import get_db
from app.models.entities import User
from app.services.llm import get_llm_client
from app.services.pipeline import sync_sources_table
from app.services.runtime_settings import resolved_settings
from app.services.sources_config import SourceConfigError, load_sources, save_sources
from app.services.sources_suggest import suggest_sources

router = APIRouter(prefix="/api/sources", tags=["sources"])
logger = logging.getLogger(__name__)


def sources_file_path() -> Path:
    return Path(get_settings().sources_config_path)


def _http_from_config_error(exc: SourceConfigError) -> HTTPException:
    if str(exc) == "jina_not_configured":
        return HTTPException(status_code=400, detail="jina_not_configured")
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/config")
async def get_sources_config(
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    try:
        return {"sources": load_sources(sources_file_path())}
    except SourceConfigError as exc:
        raise _http_from_config_error(exc) from exc


@router.put("/config")
async def put_sources_config(
    body: SourcesConfigBody,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    try:
        save_sources(sources_file_path(), body.sources)
        await sync_sources_table(session)
    except SourceConfigError as exc:
        raise _http_from_config_error(exc) from exc
    return {"sources": load_sources(sources_file_path())}


async def _jina_search(query: str) -> str:
    rs = resolved_settings()
    url = "https://s.jina.ai/" + quote(query, safe="")
    headers = {
        "Authorization": f"Bearer {rs['jina_api_key']}",
        "Accept": "application/json",
        # Titles and URLs are enough to draft a source. Full page bodies
        # are hundreds of KB and often exceed the 30s client timeout.
        "X-Respond-With": "no-content",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.text


async def _llm_complete(prompt: str) -> str:
    llm = get_llm_client()
    answer = await llm.chat(
        [
            {"role": "system", "content": "You output only a JSON array."},
            {"role": "user", "content": prompt},
        ],
        stream=False,
        reasoning=False,
    )
    if not isinstance(answer, str):
        raise RuntimeError("LLM returned no text")
    return answer


@router.post("/suggest")
async def suggest_sources_api(
    body: SourceSuggestBody,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    rs = resolved_settings()
    try:
        existing = load_sources(sources_file_path())
    except SourceConfigError:
        existing = []
    try:
        return await suggest_sources(
            mode=body.mode,
            query=body.query,
            existing=existing,
            jina_api_key=str(rs.get("jina_api_key") or ""),
            search=_jina_search,
            complete=_llm_complete,
        )
    except SourceConfigError as exc:
        raise _http_from_config_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.TimeoutException as exc:
        logger.warning("source suggest timed out")
        raise HTTPException(status_code=502, detail="suggest_timeout") from exc
    except Exception as exc:
        logger.exception("source suggest failed")
        raise HTTPException(status_code=502, detail="suggest_failed") from exc
