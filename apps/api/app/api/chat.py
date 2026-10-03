from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import ChatRequest, ChatResponse
from app.core.db import get_db
from app.models.entities import User
from app.services.chat import (
    answer_question,
    delete_session,
    extract_upload,
    get_session_detail,
    list_sessions,
)
from app.services.usage import usage_user

router = APIRouter(prefix="/api/chat", tags=["chat"])
log = logging.getLogger("chat")

_UPLOAD_STATUS = {
    "file_too_large": 413,
    "unsupported_type": 400,
    "no_text": 422,
}


@router.get("/sessions")
async def chat_sessions(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    items = await list_sessions(db, user.id)
    return {"items": items}


@router.get("/sessions/{session_id}")
async def chat_session_detail(
    session_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    detail = await get_session_detail(db, user.id, session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="session_not_found")
    return detail


@router.delete("/sessions/{session_id}", status_code=204)
async def chat_session_delete(
    session_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    removed = await delete_session(db, user.id, session_id)
    if not removed:
        raise HTTPException(status_code=404, detail="session_not_found")
    return Response(status_code=204)


@router.post("/extract")
async def chat_extract(
    user: Annotated[User, Depends(get_current_user)],
    file: UploadFile = File(...),
) -> dict:
    data = await file.read()
    try:
        return extract_upload(file.filename or "upload", data)
    except ValueError as exc:
        code = str(exc)
        raise HTTPException(status_code=_UPLOAD_STATUS.get(code, 400), detail=code) from exc


@router.post("")
async def chat(
    body: ChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ChatResponse:
    ks = body.knowledge_source
    if ks not in ("local", "local_and_dify", "dify"):
        raise HTTPException(status_code=400, detail="Invalid knowledge_source")
    session_id = uuid.UUID(body.session_id) if body.session_id else None
    log.info("chat start user=%s q_len=%s source=%s files=%s", user.username, len(body.question), ks, len(body.attachments))
    try:
        with usage_user(user.id):
            result = await answer_question(
                db,
                user_id=user.id,
                question=body.question,
                knowledge_source=ks,  # type: ignore[arg-type]
                session_id=session_id,
                locale=body.locale,
                programme=body.programme,
                topic=body.topic,
                attachments=[att.model_dump() for att in body.attachments],
            )
        log.info("chat done cites=%s truncated=%s", len(result.get("citations") or []), result.get("truncated"))
        return ChatResponse.model_validate(result)
    except Exception as exc:
        log.exception("chat failed")
        raise HTTPException(status_code=502, detail=f"Chat failed: {exc}") from exc
