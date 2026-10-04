"""Tests for local_min_score filtering of weak retrieval hits."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import chat as chat_service
from app.services.query_rewrite import filter_hits_by_min_score
from app.services.runtime_settings import apply_patch


def test_filter_hits_by_min_score_drops_weak():
    hits = [
        {"document_id": "a", "chunk_index": 0, "score": 0.8, "title": "high"},
        {"document_id": "b", "chunk_index": 0, "score": 0.12, "title": "noise"},
        {"document_id": "c", "chunk_index": 0, "score": 0.25, "title": "edge"},
    ]
    kept = filter_hits_by_min_score(hits, 0.25)
    assert [h["title"] for h in kept] == ["high", "edge"]


def test_filter_hits_by_min_score_zero_keeps_all():
    hits = [{"score": 0.01}, {"score": 0.99}]
    assert filter_hits_by_min_score(hits, 0) == hits
    assert filter_hits_by_min_score(hits, -1) == hits


@pytest.mark.parametrize("value", [0, 0.0, 0.25, 1, 1.0])
def test_apply_patch_accepts_local_min_score(value):
    current = {"local_min_score": 0.25}
    new, warnings = apply_patch(current, {"local_min_score": value})
    assert new["local_min_score"] == float(value)
    assert warnings == []


@pytest.mark.parametrize("value", [-0.1, 1.5, "0.25", True, None])
def test_apply_patch_rejects_local_min_score(value):
    with pytest.raises(ValueError, match="local_min_score"):
        apply_patch({"local_min_score": 0.25}, {"local_min_score": value})


def _session_mock() -> MagicMock:
    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    empty = MagicMock()
    empty.all.return_value = []
    session.scalars = AsyncMock(return_value=empty)
    return session


@pytest.mark.asyncio
async def test_answer_question_applies_local_min_score(monkeypatch):
    captured: dict[str, Any] = {}
    weak = [
        {
            "document_id": str(uuid.uuid4()),
            "title": "無關幼稚園",
            "circular_no": "EDBCM1/2026",
            "issued_at": "2026-01-01",
            "source_url": "https://example.test/1",
            "content": "幼稚園活動",
            "chunk_index": 0,
            "score": 0.12,
            "backend": "local",
        },
        {
            "document_id": str(uuid.uuid4()),
            "title": "相關通告",
            "circular_no": "EDBCM2/2026",
            "issued_at": "2026-01-02",
            "source_url": "https://example.test/2",
            "content": "津貼說明",
            "chunk_index": 0,
            "score": 0.72,
            "backend": "local",
        },
    ]

    class FakeLocal:
        async def retrieve(self, session, query, top_k=8, **kwargs):
            return [dict(h) for h in weak[:top_k]]

    class FakeLlm:
        async def chat(self, messages, stream=False, **kwargs):
            captured["messages"] = messages
            return "測試回答"

    monkeypatch.setattr(
        chat_service,
        "get_merged",
        AsyncMock(
            return_value={
                "local_top_k": 10,
                "local_min_score": 0.25,
                "dify_top_k": 5,
                "system_prompt": "系統提示",
                "cite_inline_refs": True,
            }
        ),
    )
    monkeypatch.setattr(chat_service, "get_local_knowledge", lambda: FakeLocal())
    monkeypatch.setattr(chat_service, "get_llm_client", lambda: FakeLlm())
    monkeypatch.setattr(chat_service, "rewrite_retrieve_query", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_service, "generate_hyde_passage", AsyncMock(return_value=None))
    monkeypatch.setattr(
        chat_service,
        "rerank_hits",
        AsyncMock(side_effect=lambda q, hits, top_n=8: hits[:top_n]),
    )
    monkeypatch.setattr(
        chat_service,
        "build_system_prompt",
        lambda rs, programme=None, topic=None: "系統提示",
    )

    result = await chat_service.answer_question(
        _session_mock(),
        user_id=uuid.uuid4(),
        question="TRG 是什麼？",
        knowledge_source="local",
        locale="zh-HK",
    )
    assert len(result["citations"]) == 1
    assert result["citations"][0]["title"] == "相關通告"
    user = captured["messages"][-1]["content"]
    assert "相關通告" in user
    assert "無關幼稚園" not in user
