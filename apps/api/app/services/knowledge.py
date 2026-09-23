"""Knowledge backend seam — local pgvector required; Dify optional."""

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.dify import get_dify_sync
from app.services.rag import retrieve_chunks


class KnowledgeBackend(Protocol):
    async def retrieve(self, session: AsyncSession, query: str, top_k: int = 8) -> list[dict[str, Any]]: ...


class LocalPgvectorBackend:
    async def retrieve(
        self,
        session: AsyncSession,
        query: str,
        top_k: int = 8,
        *,
        programme: str | None = None,
        topic: str | None = None,
    ) -> list[dict[str, Any]]:
        hits = await retrieve_chunks(
            session, query, top_k=top_k, programme=programme, topic=topic
        )
        for h in hits:
            h["backend"] = "local"
        return hits


class DifyKnowledgeBackend:
    async def retrieve(self, session: AsyncSession, query: str, top_k: int = 8) -> list[dict[str, Any]]:
        return await get_dify_sync().retrieve(query, top_k=top_k)


def get_local_knowledge() -> LocalPgvectorBackend:
    return LocalPgvectorBackend()


def get_dify_knowledge() -> DifyKnowledgeBackend:
    return DifyKnowledgeBackend()
