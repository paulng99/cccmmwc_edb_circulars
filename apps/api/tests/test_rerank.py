"""Unit tests for Jina rerank ordering and no-key fallback."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.services import rerank as rerank_mod


def _hits() -> list[dict[str, Any]]:
    return [
        {
            "document_id": "d1",
            "chunk_index": 0,
            "title": "無關通告",
            "content": "其他內容",
            "score": 0.9,
        },
        {
            "document_id": "d2",
            "chunk_index": 0,
            "title": "全方位學習及姊妹學校津貼2026/27學年津貼額",
            "content": "小學 $990 中學 $1,350",
            "score": 0.5,
        },
        {
            "document_id": "d3",
            "chunk_index": 1,
            "title": "姊妹學校交流",
            "content": "交流活動",
            "score": 0.4,
        },
    ]


@pytest.mark.asyncio
async def test_rerank_hits_noop_without_api_key(monkeypatch):
    monkeypatch.setattr(
        rerank_mod,
        "resolved_settings",
        lambda: {"jina_api_key": "", "jina_reranker_model": "jina-reranker-v2-base-multilingual"},
    )
    hits = _hits()
    out = await rerank_mod.rerank_hits("LWLSSG 津貼額", hits, top_n=2)
    assert [h["document_id"] for h in out] == ["d1", "d2"]


@pytest.mark.asyncio
async def test_rerank_hits_orders_by_api_results(monkeypatch):
    monkeypatch.setattr(
        rerank_mod,
        "resolved_settings",
        lambda: {
            "jina_api_key": "secret",
            "jina_reranker_model": "jina-reranker-v2-base-multilingual",
        },
    )
    monkeypatch.setattr(rerank_mod, "record_usage", AsyncMock())

    class FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "model": "jina-reranker-v2-base-multilingual",
                "usage": {"total_tokens": 12},
                "results": [
                    {"index": 1, "relevance_score": 0.95},
                    {"index": 2, "relevance_score": 0.4},
                    {"index": 0, "relevance_score": 0.1},
                ],
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, headers=None, json=None):
            assert url.endswith("/v1/rerank")
            assert json["query"] == "LWLSSG 津貼額"
            assert len(json["documents"]) == 3
            return FakeResp()

    monkeypatch.setattr(rerank_mod.httpx, "AsyncClient", FakeClient)

    out = await rerank_mod.rerank_hits("LWLSSG 津貼額", _hits(), top_n=2)
    assert [h["document_id"] for h in out] == ["d2", "d3"]
    assert out[0]["score"] == pytest.approx(0.95)
    assert out[0]["match"] == "rerank"


@pytest.mark.asyncio
async def test_rerank_hits_http_error_keeps_order(monkeypatch):
    monkeypatch.setattr(
        rerank_mod,
        "resolved_settings",
        lambda: {"jina_api_key": "secret", "jina_reranker_model": "x"},
    )

    class BoomClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            raise RuntimeError("network")

    monkeypatch.setattr(rerank_mod.httpx, "AsyncClient", BoomClient)
    hits = _hits()
    out = await rerank_mod.rerank_hits("q", hits, top_n=2)
    assert [h["document_id"] for h in out] == ["d1", "d2"]
