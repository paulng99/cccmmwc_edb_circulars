"""Optional Dify Knowledge sync — no-op when DIFY_ENABLED=false."""

from __future__ import annotations

from typing import Protocol

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Document
from app.services.runtime_settings import resolved_settings
from app.services.storage import get_object_bytes


class DifySync(Protocol):
    async def sync_document(self, session: AsyncSession, doc: Document) -> None: ...

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict]: ...


class NoOpDifySync:
    async def sync_document(self, session: AsyncSession, doc: Document) -> None:
        return None

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        return []


class HttpDifySync:
    async def sync_document(self, session: AsyncSession, doc: Document) -> None:
        rs = resolved_settings()
        if not doc.storage_key or not rs.get("dify_dataset_id"):
            return
        raw = get_object_bytes(doc.storage_key)
        headers = {
            "Authorization": f"Bearer {rs['dify_dataset_api_key']}",
        }
        files = {"file": (f"{doc.id}.pdf", raw, doc.mime_type or "application/pdf")}
        data = {
            "indexing_technique": "high_quality",
            "process_rule": '{"mode":"automatic"}',
        }
        url = (
            f"{str(rs['dify_api_url']).rstrip('/')}/v1/datasets/"
            f"{rs['dify_dataset_id']}/document/create-by-file"
        )
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, headers=headers, data=data, files=files)
            if resp.status_code >= 400:
                return
            body = resp.json()
            doc_id = (body.get("document") or {}).get("id")
            if doc_id:
                doc.dify_document_id = doc_id
                await session.commit()

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        rs = resolved_settings()
        if not rs.get("dify_dataset_id"):
            return []
        headers = {
            "Authorization": f"Bearer {rs['dify_dataset_api_key']}",
            "Content-Type": "application/json",
        }
        url = (
            f"{str(rs['dify_api_url']).rstrip('/')}/v1/datasets/"
            f"{rs['dify_dataset_id']}/retrieve"
        )
        payload = {
            "query": query,
            "retrieval_model": {
                "search_method": "hybrid_search",
                "reranking_enable": False,
                "top_k": top_k,
            },
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                return []
            records = resp.json().get("records") or []
            out = []
            for rec in records:
                seg = rec.get("segment") or {}
                out.append(
                    {
                        "content": seg.get("content", ""),
                        "title": (seg.get("document") or {}).get("name"),
                        "score": rec.get("score"),
                        "source": "dify",
                    }
                )
            return out


def get_dify_sync() -> DifySync:
    rs = resolved_settings()
    if rs.get("dify_enabled"):
        return HttpDifySync()
    return NoOpDifySync()
