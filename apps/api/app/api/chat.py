from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import ChatRequest
from app.core.db import get_db
from app.models.entities import User
from app.services.chat import answer_question

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("")
async def chat(
    body: ChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    ks = body.knowledge_source
    if ks not in ("local", "local_and_dify", "dify"):
        raise HTTPException(status_code=400, detail="Invalid knowledge_source")
    session_id = uuid.UUID(body.session_id) if body.session_id else None
    return await answer_question(
        db,
        user_id=user.id,
        question=body.question,
        knowledge_source=ks,  # type: ignore[arg-type]
        session_id=session_id,
        locale=body.locale,
    )
