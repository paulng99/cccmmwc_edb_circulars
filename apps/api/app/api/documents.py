from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import DocumentGroupOut, DocumentOut, DocumentVariantOut
from app.collectors.circular_meta import is_language_label
from app.core.db import get_db
from app.models.entities import Document, User
from app.services.storage import get_object_bytes

router = APIRouter(prefix="/api/documents", tags=["documents"])

_LANG_RANK = {"zh-HK": 0, "zh-CN": 1, "en": 2}


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


def _group_key(doc: Document) -> str:
    circ = (doc.circular_no or "").strip()
    if circ and circ.upper().startswith("EDBC"):
        return circ.upper()
    return f"id:{doc.id}"


def _pick_title(docs: list[Document]) -> str:
    ranked = sorted(
        docs,
        key=lambda d: (
            0 if not is_language_label(d.title) else 1,
            _LANG_RANK.get(d.language, 9),
        ),
    )
    for d in ranked:
        if d.title and not is_language_label(d.title):
            return d.title
    return ranked[0].title if ranked else "Untitled"


def _to_groups(docs: list[Document]) -> list[DocumentGroupOut]:
    buckets: dict[str, list[Document]] = {}
    for d in docs:
        buckets.setdefault(_group_key(d), []).append(d)

    groups: list[DocumentGroupOut] = []
    for key, members in buckets.items():
        members_sorted = sorted(
            members,
            key=lambda d: (_LANG_RANK.get(d.language, 9), str(d.id)),
        )
        primary = members_sorted[0]
        for d in members_sorted:
            if not is_language_label(d.title):
                primary = d
                break
        issued = max((d.issued_at for d in members_sorted if d.issued_at), default=None)
        circular = next((d.circular_no for d in members_sorted if d.circular_no), None)
        groups.append(
            DocumentGroupOut(
                key=key,
                title=_pick_title(members_sorted),
                circular_no=circular,
                issued_at=issued.isoformat() if issued else None,
                source_id=primary.source_id,
                primary_id=str(primary.id),
                variants=[
                    DocumentVariantOut(
                        id=str(d.id),
                        language=d.language,
                        status=d.status,
                        file_size=d.file_size,
                        title=d.title,
                    )
                    for d in members_sorted
                ],
            )
        )

    groups.sort(
        key=lambda g: (
            g.issued_at or "",
            g.circular_no or "",
        ),
        reverse=True,
    )
    return groups


@router.get("")
async def list_documents(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    q: Optional[str] = None,
    source_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    grouped: bool = Query(True),
) -> dict:
    stmt = select(Document)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Document.title.ilike(like), Document.circular_no.ilike(like)))
    if source_id:
        stmt = stmt.where(Document.source_id == source_id)
    stmt = stmt.order_by(Document.issued_at.desc().nullslast(), Document.created_at.desc())
    rows = list((await db.scalars(stmt)).all())

    if not grouped:
        total = len(rows)
        page_rows = rows[(page - 1) * page_size : page * page_size]
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "grouped": False,
            "items": [_to_out(d) for d in page_rows],
        }

    groups = _to_groups(rows)
    total = len(groups)
    page_groups = groups[(page - 1) * page_size : page * page_size]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "grouped": True,
        "file_count": len(rows),
        "items": [g.model_dump() for g in page_groups],
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
    filename = f"{doc.circular_no or doc.id}.pdf"
    return Response(
        content=data,
        media_type=doc.mime_type or "application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
