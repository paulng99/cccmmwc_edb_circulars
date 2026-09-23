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
    import logging

    log = logging.getLogger("chat")
    ks = body.knowledge_source
    if ks not in ("local", "local_and_dify", "dify"):
        raise HTTPException(status_code=400, detail="Invalid knowledge_source")
    session_id = uuid.UUID(body.session_id) if body.session_id else None
    log.info("chat start user=%s q_len=%s source=%s", user.username, len(body.question), ks)
    try:
        result = await answer_question(
            db,
            user_id=user.id,
            question=body.question,
            knowledge_source=ks,  # type: ignore[arg-type]
            session_id=session_id,
            locale=body.locale,
        )
        log.info("chat done cites=%s", len(result.get("citations") or []))
        return result
    except Exception as exc:
        log.exception("chat failed")
        raise HTTPException(status_code=502, detail=f"Chat failed: {exc}") from exc
