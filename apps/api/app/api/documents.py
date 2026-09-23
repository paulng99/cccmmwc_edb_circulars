from __future__ import annotations

import uuid
from pathlib import PurePosixPath
from typing import Annotated, Optional
from urllib.parse import urlparse

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


def _download_filename(doc: Document) -> str:
    if doc.file_url:
        name = PurePosixPath(urlparse(doc.file_url).path).name
        if name.lower().endswith(".pdf"):
            return name
    raw = (doc.circular_no or str(doc.id)).replace("/", "-")
    return f"{raw}.pdf"


_CIRCULAR_SOURCES = frozenset({"edb_circulars"})


def document_category(doc: Document) -> str:
    """Classify as circular (通告) or document (文件)."""
    circ = (doc.circular_no or "").strip().upper()
    if doc.source_id in _CIRCULAR_SOURCES or circ.startswith("EDBC"):
        return "circular"
    return "document"


def _to_out(doc: Document) -> DocumentOut:
    extra = doc.extra or {}
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
        index_error=(extra.get("index_error") or None),
        warning=(extra.get("warning") or None),
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
                category=document_category(primary),
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
    status_filter: Optional[str] = Query(None, alias="status"),
    category: Optional[str] = Query(None, description="all | circular | document"),
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
    if status_filter:
        stmt = stmt.where(Document.status == status_filter)
    if category in ("circular", "document"):
        is_circular = or_(
            Document.source_id.in_(list(_CIRCULAR_SOURCES)),
            Document.circular_no.ilike("EDBC%"),
        )
        if category == "circular":
            stmt = stmt.where(is_circular)
        else:
            stmt = stmt.where(~is_circular)
    stmt = stmt.order_by(Document.issued_at.desc().nullslast(), Document.created_at.desc())
    rows = list((await db.scalars(stmt)).all())

    if not grouped or status_filter == "failed":
        total = len(rows)
        page_rows = rows[(page - 1) * page_size : page * page_size]
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "grouped": False,
            "category": category or "all",
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
        "category": category or "all",
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
    filename = _download_filename(doc)
    return Response(
        content=data,
        media_type=doc.mime_type or "application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
