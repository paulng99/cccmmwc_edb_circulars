from __future__ import annotations

import uuid
from pathlib import PurePosixPath
from typing import Annotated, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import DocumentOut
from app.core.db import get_db
from app.models.entities import Document, User
from app.services.storage import get_object_bytes

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _download_filename(doc: Document) -> str:
    if doc.file_url:
        name = PurePosixPath(urlparse(doc.file_url).path).name
        if name.lower().endswith(".pdf"):
            return name
    raw = (doc.circular_no or str(doc.id)).replace("/", "-")
    return f"{raw}.pdf"


def _to_out(doc: Document) -> DocumentOut:
    return DocumentOut(
        id=str(doc.id),
        source_id=doc.source_id,
        title=doc.title,
        circular_no=doc.circular_no,
        issued_at=doc.issued_at.isoformat() if doc.issued_at else None,
        language=doc.language,
        source_url=doc.source_url,
        file_url=doc.file_url,
        status=doc.status,
        file_size=doc.file_size,
    )


@router.get("")
async def list_documents(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    q: Optional[str] = None,
    source_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    stmt = select(Document)
    count_stmt = select(func.count()).select_from(Document)
    if q:
        like = f"%{q}%"
        filt = or_(Document.title.ilike(like), Document.circular_no.ilike(like))
        stmt = stmt.where(filt)
        count_stmt = count_stmt.where(filt)
    if source_id:
        stmt = stmt.where(Document.source_id == source_id)
        count_stmt = count_stmt.where(Document.source_id == source_id)
    total = await db.scalar(count_stmt) or 0
    stmt = stmt.order_by(Document.issued_at.desc().nullslast(), Document.created_at.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.scalars(stmt)).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_to_out(d) for d in rows],
    }


@router.get("/{document_id}")
async def get_document(
    document_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> DocumentOut:
    doc = await db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return _to_out(doc)


@router.get("/{document_id}/file")
async def download_file(
    document_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    doc = await db.get(Document, document_id)
    if not doc or not doc.storage_key:
        raise HTTPException(status_code=404, detail="File not found")
    data = get_object_bytes(doc.storage_key)
    filename = _download_filename(doc)
    return Response(
        content=data,
        media_type=doc.mime_type or "application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
