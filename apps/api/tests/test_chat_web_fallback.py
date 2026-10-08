"""Chat falls back to the public web only when the local library has no hits."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import chat as chat_service
from app.services.chat import build_chat_messages
from app.services.web_search import WebSearchOutcome


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


def _patch_common(monkeypatch, *, retrieve_hits: list[dict[str, Any]]):
    class FakeLocal:
        async def retrieve(self, session, query, top_k=8, **kwargs):
            return [dict(hit) for hit in retrieve_hits[:top_k]]

    class FakeLlm:
        async def chat(self, messages, stream=False, **kwargs):
            captured["messages"] = messages
            return "測試回答"

    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        chat_service,
        "get_merged",
        AsyncMock(
            return_value={
                "local_top_k": 8,
                "local_min_score": 0,
                "dify_top_k": 4,
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
    return captured


def test_web_fallback_prompt_requires_online_label():
    messages = build_chat_messages(
        system="SYS",
        lang_hint="Respond in Traditional Chinese (Hong Kong).",
        question="課程更新有甚麼安排？",
        context_blocks=["[W1] 教育局網頁 | https://www.edb.gov.hk/x\n摘要"],
        web_fallback=True,
    )
    user = messages[-1]["content"]
    assert "PUBLIC WEB SEARCH" in user
    assert "NOT from the local circular library" in user
    assert "[W1]" in user
    assert "課程更新有甚麼安排？" in user


def test_web_empty_prompt_does_not_invent():
    messages = build_chat_messages(
        system="SYS",
        lang_hint="Respond in English.",
        question="未知題目",
        context_blocks=[],
        web_searched_empty=True,
    )
    user = messages[-1]["content"]
    assert "public web search" in user.lower()
    assert "Do not invent" in user


def test_local_hits_are_not_described_as_web():
    messages = build_chat_messages(
        system="SYS",
        lang_hint="Respond in English.",
        question="津貼",
        context_blocks=["[L1] 通告\n正文"],
    )
    user = messages[-1]["content"]
    assert "local circular library" in user
    assert "PUBLIC WEB SEARCH" not in user


@pytest.mark.asyncio
async def test_answer_question_uses_web_when_library_empty(monkeypatch):
    captured = _patch_common(monkeypatch, retrieve_hits=[])
    searched: dict[str, Any] = {}

    async def fake_search(query: str):
        searched["query"] = query
        return WebSearchOutcome(
            results=[
                {
                    "title": "教育局網頁",
                    "url": "https://www.edb.gov.hk/tc/example",
                    "content": "公開摘要",
                }
            ],
            attempted=True,
        )

    monkeypatch.setattr(chat_service, "search_web", fake_search)
    result = await chat_service.answer_question(
        _session_mock(),
        user_id=uuid.uuid4(),
        question="最近的課程更新",
        knowledge_source="local",
        locale="zh-HK",
    )
    assert result["web_fallback"] is True
    assert result["citations"][0]["backend"] == "web"
    assert result["citations"][0]["ref"] == "W1"
    assert result["citations"][0]["source_url"] == "https://www.edb.gov.hk/tc/example"
    assert "document_id" not in result["citations"][0]
    user = captured["messages"][-1]["content"]
    assert "PUBLIC WEB SEARCH" in user
    assert "公開摘要" in user
    assert searched["query"] == "最近的課程更新"
    system = captured["messages"][0]["content"]
    assert "online information" in system


@pytest.mark.asyncio
async def test_answer_question_skips_web_when_local_hits_exist(monkeypatch):
    captured = _patch_common(
        monkeypatch,
        retrieve_hits=[
            {
                "document_id": str(uuid.uuid4()),
                "title": "本機通告",
                "circular_no": "EDBCM048/2026",
                "issued_at": "2026-03-01",
                "source_url": "https://example.test/local",
                "content": "本機正文",
                "chunk_index": 0,
                "score": 0.8,
            }
        ],
    )

    async def should_not_search(_query: str):
        raise AssertionError("web search should not run when local circulars match")

    monkeypatch.setattr(chat_service, "search_web", should_not_search)
    result = await chat_service.answer_question(
        _session_mock(),
        user_id=uuid.uuid4(),
        question="EDBCM048/2026 重點",
        knowledge_source="local",
        locale="zh-HK",
    )
    assert result["web_fallback"] is False
    assert result["citations"][0]["backend"] == "local"
    assert "PUBLIC WEB SEARCH" not in captured["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_prompt_only_does_not_search_the_web(monkeypatch):
    _patch_common(monkeypatch, retrieve_hits=[])

    async def should_not_search(_query: str):
        raise AssertionError("blank questions should not search the web")

    monkeypatch.setattr(chat_service, "search_web", should_not_search)
    result = await chat_service.answer_question(
        _session_mock(),
        user_id=uuid.uuid4(),
        question="   ",
        knowledge_source="local",
        locale="en",
    )
    assert result["web_fallback"] is False
    assert result["citations"] == []
    assert result["prompt_only"] is True
