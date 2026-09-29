from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.entities import User
from app.services.usage import usage_report

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("")
async def get_usage(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    days: int | None = Query(default=None, ge=1, le=366),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> dict:
    del user
    return await usage_report(session, days=days, date_from=date_from, date_to=date_to)
