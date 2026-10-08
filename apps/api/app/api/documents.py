from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from pathlib import PurePosixPath
from typing import Annotated, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import (
    CalendarDayOut,
    CalendarEventOut,
    DocumentActivityOut,
    DocumentGroupOut,
    DocumentOut,
    DocumentVariantOut,
)
from app.collectors.circular_meta import is_language_label
from app.core.db import get_db
from app.models.entities import Document, DocumentChunk, User
from app.services.classify import PROGRAMMES, TOPICS, programme_for
from app.services.storage import get_object_bytes

_HK = ZoneInfo("Asia/Hong_Kong")

router = APIRouter(prefix="/api/documents", tags=["documents"])

_LANG_RANK = {"zh-HK": 0, "zh-CN": 1, "en": 2}
SORT_ISSUED = "issued_at"
SORT_REVISED = "revised_at"
SORT_DOWNLOADED = "downloaded_at"
_SORT_FIELDS = frozenset({SORT_ISSUED, SORT_REVISED, SORT_DOWNLOADED})


def _normalize_sort(sort_by: str | None, sort_dir: str | None) -> tuple[str, bool]:
    field = sort_by if sort_by in _SORT_FIELDS else SORT_ISSUED
    descending = (sort_dir or "desc").lower() != "asc"
    return field, descending


def _iso_ts(value) -> str | None:
    if value is None:
        return None
    iso = value.isoformat()
    return iso


def _group_downloaded_at(docs: list[Document]) -> str | None:
    times = [d.created_at for d in docs if d.created_at]
    if not times:
        return None
    return max(times).isoformat()


def _group_revised_at(docs: list[Document]) -> str | None:
    dates = [d.revised_at for d in docs if d.revised_at]
    if not dates:
        return None
    return max(dates).isoformat()


def _sort_groups(groups: list[DocumentGroupOut], sort_by: str, descending: bool) -> list[DocumentGroupOut]:
    def value(g: DocumentGroupOut) -> str:
        if sort_by == SORT_DOWNLOADED:
            return g.downloaded_at or ""
        if sort_by == SORT_REVISED:
            return g.revised_at or ""
        return g.issued_at or ""

    present = [g for g in groups if value(g)]
    missing = [g for g in groups if not value(g)]
    present.sort(key=lambda g: (value(g), g.circular_no or "", g.key), reverse=descending)
    missing.sort(key=lambda g: (g.circular_no or "", g.key), reverse=descending)
    return present + missing


def _download_filename(doc: Document) -> str:
    if doc.file_url:
        name = PurePosixPath(urlparse(doc.file_url).path).name
        if name.lower().endswith(".pdf"):
            return name
    raw = (doc.circular_no or str(doc.id)).replace("/", "-")
    return f"{raw}.pdf"


def _doc_programme(doc: Document) -> str:
    stored = (doc.programme or "").strip()
    if stored in PROGRAMMES:
        return stored
    return programme_for(source_id=doc.source_id, circular_no=doc.circular_no)


def _doc_topics(doc: Document) -> list[str]:
    raw = doc.topics if isinstance(doc.topics, list) else []
    return [t for t in raw if t in TOPICS]


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_activities(raw: object) -> list[DocumentActivityOut]:
    if not isinstance(raw, list):
        return []
    out: list[DocumentActivityOut] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = _optional_text(item.get("name"))
        starts = item.get("starts_at")
        deadline = item.get("deadline_at")
        summary = _optional_text(item.get("summary"))
        location = _optional_text(item.get("location"))
        if not starts and not deadline and not name and not summary and not location:
            continue
        out.append(
            DocumentActivityOut(
                name=name,
                starts_at=str(starts) if starts else None,
                deadline_at=str(deadline) if deadline else None,
                summary=summary,
                location=location,
            )
        )
    return out


def _parse_iso_date(value: object) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


_DEFAULT_SUBMIT_TITLE = "交回文件"


def _activity_events_for_doc(doc: Document) -> list[CalendarEventOut]:
    """Expand each activity into separate start/deadline rows (deduped per activity+date+kind)."""
    events: list[CalendarEventOut] = []
    seen: set[tuple[str, str, str | None, str]] = set()
    for act in _normalize_activities(doc.activities):
        for kind, raw in (("start", act.starts_at), ("deadline", act.deadline_at)):
            if not raw:
                continue
            # Deadlines without a title use 「交回文件」 — never the circular title.
            if kind == "deadline":
                name = act.name or _DEFAULT_SUBMIT_TITLE
            else:
                name = act.name
            key = (raw, kind, name, str(doc.id))
            if key in seen:
                continue
            seen.add(key)
            events.append(
                CalendarEventOut(
                    date=raw,
                    kind=kind,
                    activity_name=name,
                    summary=act.summary,
                    location=act.location,
                    document_id=str(doc.id),
                    document_title=doc.title,
                    circular_no=doc.circular_no,
                )
            )
    return events


def _to_out(doc: Document, *, chunk_count: int = 0) -> DocumentOut:
    extra = doc.extra or {}
    return DocumentOut(
        id=str(doc.id),
        source_id=doc.source_id,
        title=doc.title,
        circular_no=doc.circular_no,
        issued_at=doc.issued_at.isoformat() if doc.issued_at else None,
        revised_at=doc.revised_at.isoformat() if doc.revised_at else None,
        downloaded_at=_iso_ts(doc.created_at),
        activities=_normalize_activities(doc.activities),
        language=doc.language,
        source_url=doc.source_url,
        file_url=doc.file_url,
        status=doc.status,
        file_size=doc.file_size,
        chunk_count=chunk_count,
        programme=_doc_programme(doc),
        topics=_doc_topics(doc),
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


def _merge_topics(docs: list[Document]) -> list[str]:
    seen: list[str] = []
    for d in docs:
        for t in _doc_topics(d):
            if t not in seen:
                seen.append(t)
    return seen


def _to_groups(
    docs: list[Document],
    *,
    sort_by: str = SORT_ISSUED,
    descending: bool = True,
) -> list[DocumentGroupOut]:
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
        prog = _doc_programme(primary)
        groups.append(
            DocumentGroupOut(
                key=key,
                title=_pick_title(members_sorted),
                circular_no=circular,
                issued_at=issued.isoformat() if issued else None,
                revised_at=_group_revised_at(members_sorted),
                downloaded_at=_group_downloaded_at(members_sorted),
                source_id=primary.source_id,
                primary_id=str(primary.id),
                programme=prog,
                category="circular" if prog == "circular" else "document",
                topics=_merge_topics(members_sorted),
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

    return _sort_groups(groups, sort_by, descending)


@router.get("")
async def list_documents(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    q: Optional[str] = None,
    source_id: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    category: Optional[str] = Query(
        None, description="legacy: all | circular | document"
    ),
    programme: Optional[str] = Query(
        None, description="all | circular | sister_school | lwlssg | other"
    ),
    topic: Optional[str] = Query(None, description="topic id from closed vocab"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    grouped: bool = Query(True),
    sort_by: Optional[str] = Query(None, description="issued_at | revised_at | downloaded_at"),
    sort_dir: Optional[str] = Query(None, description="desc | asc"),
) -> dict:
    field, descending = _normalize_sort(sort_by, sort_dir)
    stmt = select(Document)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Document.title.ilike(like), Document.circular_no.ilike(like)))
    if source_id:
        stmt = stmt.where(Document.source_id == source_id)
    if status_filter:
        stmt = stmt.where(Document.status == status_filter)

    prog = (programme or "").strip()
    if prog in PROGRAMMES:
        stmt = stmt.where(Document.programme == prog)
    elif category in ("circular", "document"):
        # Backward compatible: circular vs non-circular
        if category == "circular":
            stmt = stmt.where(Document.programme == "circular")
        else:
            stmt = stmt.where(Document.programme != "circular")

    topic_id = (topic or "").strip()
    if topic_id in TOPICS:
        stmt = stmt.where(Document.topics.contains([topic_id]))

    if field == SORT_DOWNLOADED:
        sort_col = Document.created_at
    elif field == SORT_REVISED:
        sort_col = Document.revised_at
    else:
        sort_col = Document.issued_at
    if descending:
        stmt = stmt.order_by(sort_col.desc().nullslast(), Document.created_at.desc())
    else:
        stmt = stmt.order_by(sort_col.asc().nullslast(), Document.created_at.asc())
    rows = list((await db.scalars(stmt)).all())

    if not grouped or status_filter == "failed":
        total = len(rows)
        page_rows = rows[(page - 1) * page_size : page * page_size]
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "grouped": False,
            "programme": prog or "all",
            "topic": topic_id or "all",
            "category": category or "all",
            "sort_by": field,
            "sort_dir": "desc" if descending else "asc",
            "items": [_to_out(d) for d in page_rows],
        }

    groups = _to_groups(rows, sort_by=field, descending=descending)
    total = len(groups)
    page_groups = groups[(page - 1) * page_size : page * page_size]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "grouped": True,
        "programme": prog or "all",
        "topic": topic_id or "all",
        "category": category or "all",
        "sort_by": field,
        "sort_dir": "desc" if descending else "asc",
        "file_count": len(rows),
        "items": [g.model_dump() for g in page_groups],
    }


@router.get("/calendar/upcoming-deadlines")
async def upcoming_deadlines(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    days: int = Query(7, ge=0, le=90),
) -> dict:
    """Deadlines from today through today+days (Asia/Hong_Kong), one row per activity."""
    today = datetime.now(_HK).date()
    end = today + timedelta(days=days)
    rows = list((await db.scalars(select(Document))).all())
    events: list[CalendarEventOut] = []
    for doc in rows:
        for ev in _activity_events_for_doc(doc):
            if ev.kind != "deadline":
                continue
            d = _parse_iso_date(ev.date)
            if d is None or d < today or d > end:
                continue
            events.append(ev)
    events.sort(key=lambda e: (e.date, e.activity_name or "", e.document_title, e.document_id))
    return {
        "from": today.isoformat(),
        "to": end.isoformat(),
        "items": [e.model_dump() for e in events],
    }


@router.get("/calendar/events")
async def calendar_events(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """All activity start/deadline events grouped by date."""
    rows = list((await db.scalars(select(Document))).all())
    by_day: dict[str, list[CalendarEventOut]] = {}
    for doc in rows:
        for ev in _activity_events_for_doc(doc):
            by_day.setdefault(ev.date, []).append(ev)
    days: list[CalendarDayOut] = []
    for day in sorted(by_day.keys()):
        day_events = by_day[day]
        day_events.sort(
            key=lambda e: (
                0 if e.kind == "start" else 1,
                e.activity_name or "",
                e.document_title,
                e.document_id,
            )
        )
        days.append(CalendarDayOut(date=day, events=day_events))
    return {"days": [d.model_dump() for d in days]}


@router.get("/{document_id}")
async def get_document(
    document_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> DocumentOut:
    doc = await db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    chunk_count = (
        await db.scalar(
            select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == doc.id)
        )
        or 0
    )
    return _to_out(doc, chunk_count=int(chunk_count))


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
