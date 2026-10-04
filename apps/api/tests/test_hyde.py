"""Unit tests for HyDE passage generation and merge into the retrieve pool."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import chat as chat_service
from app.services import hyde as hyde_mod
from app.services.hyde import clip_hyde_passage, generate_hyde_passage
from app.services.query_rewrite import merge_multi_query_hits


def test_clip_hyde_passage_strips_fence_and_caps():
    raw = "```\n" + ("津貼額段落" * 80) + "\n```"
    out = clip_hyde_passage(raw, max_chars=40)
    assert "```" not in out
    assert len(out) <= 40
    assert out.startswith("津貼額")


def test_clip_hyde_passage_strips_preamble():
    assert clip_hyde_passage("假設段落：小學每名學生津貼為 $990。") == "小學每名學生津貼為 $990。"


@pytest.mark.asyncio
async def test_generate_hyde_passage_success(monkeypatch):
    class FakeLlm:
        async def chat(self, messages, stream=False, **kwargs):
            return "全方位學習及姊妹學校津貼2026/27學年，小學每名學生津貼額為990元。"

    monkeypatch.setattr(hyde_mod, "get_llm_client", lambda: FakeLlm())
    out = await generate_hyde_passage("LWLSSG 的學生資助")
    assert out is not None
    assert "津貼" in out
    assert "990" in out


@pytest.mark.asyncio
async def test_generate_hyde_passage_timeout_returns_none(monkeypatch):
    class FakeLlm:
        async def chat(self, messages, stream=False, **kwargs):
            import asyncio

            await asyncio.sleep(60)
            return "x"

    monkeypatch.setattr(hyde_mod, "get_llm_client", lambda: FakeLlm())
    monkeypatch.setattr(hyde_mod, "HYDE_TIMEOUT_SECONDS", 0.01)
    assert await generate_hyde_passage("LWLSSG") is None


@pytest.mark.asyncio
async def test_generate_hyde_passage_empty_question():
    assert await generate_hyde_passage("  ") is None


def test_merge_hyde_hits_into_dual_query_pool():
    dual = [
        {"document_id": "d1", "chunk_index": 0, "score": 0.55, "title": "A", "match": "hybrid"},
        {"document_id": "d2", "chunk_index": 0, "score": 0.50, "title": "B", "match": "keyword"},
    ]
    hyde = [
        {
            "document_id": "d3",
            "chunk_index": 0,
            "score": 0.80,
            "title": "津貼額",
            "match": "hyde",
        },
        {
            "document_id": "d1",
            "chunk_index": 0,
            "score": 0.70,
            "title": "A",
            "match": "hyde",
        },
    ]
    merged = merge_multi_query_hits([dual, hyde], top_k=3)
    assert merged[0]["document_id"] == "d1"
    # max(0.55, 0.70) + both boost
    assert merged[0]["score"] == pytest.approx(0.82)
    assert {h["document_id"] for h in merged} == {"d1", "d3", "d2"}


@pytest.mark.asyncio
async def test_answer_question_merges_hyde_vector_hits(monkeypatch):
    captured: dict[str, Any] = {"queries": [], "hyde_query": None}
    user_id = __import__("uuid").uuid4()

    class FakeLocal:
        async def retrieve(self, session, query, top_k=8, **kwargs):
            captured["queries"].append(query)
            return [
                {
                    "document_id": "d-dual",
                    "chunk_index": 0,
                    "title": "雙查詢命中",
                    "content": "hybrid",
                    "score": 0.4,
                    "circular_no": None,
                    "issued_at": None,
                    "source_url": None,
                }
            ]

    class FakeLlm:
        async def chat(self, messages, stream=False, **kwargs):
            return "最終回答"

        async def chat_with_meta(self, messages, stream=False, **kwargs):
            class C:
                content = "最終回答"
                finish_reason = "stop"

            return C()

    async def fake_hyde(question: str):
        captured["hyde_question"] = question
        return "假設通告：全方位學習及姊妹學校津貼小學每名學生津貼額990元。"

    async def fake_vector(session, query, top_k=8, **kwargs):
        captured["hyde_query"] = query
        return [
            {
                "document_id": "d-hyde",
                "chunk_index": 0,
                "title": "全方位學習及姊妹學校津貼2026/27學年津貼額",
                "content": "小學 $990",
                "score": 0.9,
                "match": kwargs.get("match", "hyde"),
                "circular_no": None,
                "issued_at": None,
                "source_url": None,
            }
        ]

    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    monkeypatch.setattr(chat_service, "get_local_knowledge", lambda: FakeLocal())
    monkeypatch.setattr(chat_service, "get_llm_client", lambda: FakeLlm())
    monkeypatch.setattr(
        chat_service,
        "rewrite_retrieve_query",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(chat_service, "generate_hyde_passage", fake_hyde)
    monkeypatch.setattr(chat_service, "retrieve_vector_only", fake_vector)
    monkeypatch.setattr(
        chat_service,
        "rerank_hits",
        AsyncMock(
            side_effect=lambda query, hits, top_n: hits[:top_n]
        ),
    )
    monkeypatch.setattr(
        chat_service,
        "get_merged",
        AsyncMock(
            return_value={
                "local_top_k": 5,
                "dify_top_k": 5,
                "system_prompt": "系統提示",
                "cite_inline_refs": True,
            }
        ),
    )
    monkeypatch.setattr(
        chat_service,
        "build_system_prompt",
        lambda rs, programme=None, topic=None: "系統提示",
    )
    monkeypatch.setattr(chat_service, "_history_for_llm", AsyncMock(return_value=[]))

    result = await chat_service.answer_question(
        session,
        user_id=user_id,
        question="LWLSSG 的學生資助",
        knowledge_source="local",
        locale="zh-HK",
    )
    assert captured["hyde_query"] is not None
    assert "990" in captured["hyde_query"]
    doc_ids = {c["document_id"] for c in result["citations"]}
    assert "d-hyde" in doc_ids
    assert "d-dual" in doc_ids


@pytest.mark.asyncio
async def test_answer_question_skips_hyde_on_failure(monkeypatch):
    captured: dict[str, Any] = {"vector_calls": 0}
    user_id = __import__("uuid").uuid4()

    class FakeLocal:
        async def retrieve(self, session, query, top_k=8, **kwargs):
            return [
                {
                    "document_id": "d1",
                    "chunk_index": 0,
                    "title": "僅雙查詢",
                    "content": "x",
                    "score": 0.5,
                    "circular_no": None,
                    "issued_at": None,
                    "source_url": None,
                }
            ]

    class FakeLlm:
        async def chat_with_meta(self, messages, stream=False, **kwargs):
            class C:
                content = "答"
                finish_reason = "stop"

            return C()

    async def boom_hyde(question: str):
        return None

    async def vector_should_not_run(*args, **kwargs):
        captured["vector_calls"] += 1
        return []

    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    monkeypatch.setattr(chat_service, "get_local_knowledge", lambda: FakeLocal())
    monkeypatch.setattr(chat_service, "get_llm_client", lambda: FakeLlm())
    monkeypatch.setattr(chat_service, "rewrite_retrieve_query", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_service, "generate_hyde_passage", boom_hyde)
    monkeypatch.setattr(chat_service, "retrieve_vector_only", vector_should_not_run)
    monkeypatch.setattr(
        chat_service,
        "rerank_hits",
        AsyncMock(side_effect=lambda query, hits, top_n: hits[:top_n]),
    )
    monkeypatch.setattr(
        chat_service,
        "get_merged",
        AsyncMock(
            return_value={
                "local_top_k": 5,
                "dify_top_k": 5,
                "system_prompt": "系統提示",
                "cite_inline_refs": True,
            }
        ),
    )
    monkeypatch.setattr(
        chat_service,
        "build_system_prompt",
        lambda rs, programme=None, topic=None: "系統提示",
    )
    monkeypatch.setattr(chat_service, "_history_for_llm", AsyncMock(return_value=[]))

    result = await chat_service.answer_question(
        session,
        user_id=user_id,
        question="姊妹學校津貼",
        knowledge_source="local",
        locale="zh-HK",
    )
    assert captured["vector_calls"] == 0
    assert [c["document_id"] for c in result["citations"]] == ["d1"]
