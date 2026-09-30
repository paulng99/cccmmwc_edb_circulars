from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import ImproveSystemPromptBody, SettingsResponse, SettingsUpdate
from app.core.db import get_db
from app.models import AppSetting
from app.models.entities import User
from app.services.prompt_improve import improve_system_prompt
from app.services.runtime_settings import (
    build_settings_response,
    get_merged,
    update_settings,
)
from app.services.usage import usage_user

router = APIRouter(prefix="/api/settings", tags=["settings"])
logger = logging.getLogger(__name__)


@router.get("", response_model=SettingsResponse)
async def get_settings_api(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    merged = await get_merged(session)
    row = await session.get(AppSetting, 1)
    return build_settings_response(merged, row)


@router.put("", response_model=SettingsResponse)
async def put_settings_api(
    body: SettingsUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    patch: dict[str, Any] = body.model_dump(exclude_unset=True)
    try:
        merged, warnings, row = await update_settings(session, patch, user.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return build_settings_response(merged, row, warnings=warnings)


@router.post("/improve-system-prompt")
async def improve_system_prompt_api(
    body: ImproveSystemPromptBody,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str]:
    draft = body.prompt.strip()
    if not draft:
        raise HTTPException(status_code=422, detail="prompt_empty")
    try:
        with usage_user(user.id):
            improved = await improve_system_prompt(draft)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("improve-system-prompt failed")
        raise HTTPException(status_code=502, detail="improve_failed") from exc
    return {"prompt": improved}
