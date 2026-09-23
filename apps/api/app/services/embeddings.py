from __future__ import annotations

from typing import Protocol

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.services.runtime_settings import resolved_settings


class EmbeddingBackend(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class JinaEmbeddingBackend:
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        rs = resolved_settings()
        if not rs.get("jina_api_key"):
            # Deterministic stub for local boot without keys (unit length ~ dim)
            dim = int(rs["jina_embedding_dim"])
            out: list[list[float]] = []
            for t in texts:
                seed = sum(ord(c) for c in t) % 997
                vec = [((seed + i) % 100) / 100.0 for i in range(dim)]
                out.append(vec)
            return out

        headers = {
            "Authorization": f"Bearer {rs['jina_api_key']}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": rs["jina_embedding_model"],
            "task": "text-matching",
            "dimensions": int(rs["jina_embedding_dim"]),
            "input": texts,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post("https://api.jina.ai/v1/embeddings", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            items = sorted(data["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in items]


def get_embedding_backend() -> EmbeddingBackend:
    return JinaEmbeddingBackend()
