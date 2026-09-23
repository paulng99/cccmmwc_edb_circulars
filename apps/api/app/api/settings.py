from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import SettingsResponse, SettingsUpdate
from app.core.db import get_db
from app.models import AppSetting
from app.models.entities import User
from app.services.runtime_settings import (
    build_settings_response,
    get_merged,
    update_settings,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


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
