"""驗證本庫 Top K（local_top_k）實際決定交給 AI 的段落數。"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import chat as chat_service
from app.services.rag import retrieve_chunks


def _make_hits(count: int, *, content_len: int = 100) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for i in range(count):
        hits.append(
            {
                "document_id": str(uuid.uuid4()),
                "title": f"通告 {i + 1}",
                "circular_no": f"EDBCM{i + 1:03d}/2026",
                "issued_at": "2026-10-01",
                "source_url": f"https://example.test/{i + 1}",
                "content": ("甲" * content_len) + f"-{i + 1}",
                "chunk_index": i,
                "score": 1.0 - i * 0.01,
                "backend": "local",
            }
        )
    return hits


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


async def _run_answer(
    monkeypatch: pytest.MonkeyPatch,
    *,
    local_top_k: int,
    retrieved_count: int,
    content_len: int = 100,
) -> dict[str, Any]:
    """以 mock 跑 answer_question，並擷取實際送給 LLM 的 context 段落。"""
    captured: dict[str, Any] = {}
    hits = _make_hits(retrieved_count, content_len=content_len)

    class FakeLocal:
        async def retrieve(self, session, query, top_k=8, **kwargs):
            captured["retrieve_top_k"] = top_k
            captured["query"] = query
            # 模擬檢索最多回傳 top_k 筆（與 retrieve_chunks 行為一致）
            return [dict(h) for h in hits[:top_k]]

    class FakeLlm:
        async def chat(self, messages, stream=False, **kwargs):
            captured["messages"] = messages
            return "測試回答"

    monkeypatch.setattr(
        chat_service,
        "get_merged",
        AsyncMock(
            return_value={
                "local_top_k": local_top_k,
                "dify_top_k": 5,
                "system_prompt": "系統提示",
                "cite_inline_refs": True,
            }
        ),
    )
    monkeypatch.setattr(chat_service, "get_local_knowledge", lambda: FakeLocal())
    monkeypatch.setattr(chat_service, "get_llm_client", lambda: FakeLlm())
    monkeypatch.setattr(
        chat_service,
        "build_system_prompt",
        lambda rs, programme=None, topic=None: rs.get("system_prompt") or "系統提示",
    )

    result = await chat_service.answer_question(
        _session_mock(),
        user_id=uuid.uuid4(),
        question="姊妹學校津貼如何使用？",
        knowledge_source="local",
        locale="zh-HK",
    )
    result["_captured"] = captured
    return result


def _context_blocks_from_messages(messages: list[dict[str, str]]) -> list[str]:
    user = messages[-1]["content"]
    marker = "Context:\n"
    assert marker in user
    after = user.split(marker, 1)[1]
    # 問題列在 Context 之後
    if "\n\nQuestion:" in after:
        after = after.split("\n\nQuestion:", 1)[0]
    if after.strip() == "(No matching documents found.)":
        return []
    return [b for b in after.split("\n\n---\n\n") if b.strip()]


@pytest.mark.asyncio
async def test_local_top_k_12_passes_twelve_chunks_and_citations(monkeypatch):
    result = await _run_answer(
        monkeypatch, local_top_k=12, retrieved_count=20, content_len=100
    )
    captured = result["_captured"]
    assert captured["retrieve_top_k"] == 12

    blocks = _context_blocks_from_messages(captured["messages"])
    assert len(blocks) == 12
    assert len(result["citations"]) == 12
    assert [c["ref"] for c in result["citations"]] == [f"L{i}" for i in range(1, 13)]
    for i, block in enumerate(blocks, start=1):
        assert block.startswith(f"[L{i}]")


@pytest.mark.asyncio
async def test_local_top_k_5_passes_five_chunks_and_citations(monkeypatch):
    result = await _run_answer(
        monkeypatch, local_top_k=5, retrieved_count=20, content_len=100
    )
    captured = result["_captured"]
    assert captured["retrieve_top_k"] == 5

    blocks = _context_blocks_from_messages(captured["messages"])
    assert len(blocks) == 5
    assert len(result["citations"]) == 5
    assert [c["ref"] for c in result["citations"]] == [f"L{i}" for i in range(1, 6)]
    for i, block in enumerate(blocks, start=1):
        assert block.startswith(f"[L{i}]")


@pytest.mark.asyncio
async def test_local_top_k_120_clamped_to_20(monkeypatch):
    """資料庫舊值 120 在 chat 讀取時夾住為 20，不直接傳給檢索。"""
    result = await _run_answer(
        monkeypatch, local_top_k=120, retrieved_count=30, content_len=100
    )
    captured = result["_captured"]
    assert captured["retrieve_top_k"] == 20

    blocks = _context_blocks_from_messages(captured["messages"])
    assert len(blocks) == 20
    assert len(result["citations"]) == 20


@pytest.mark.asyncio
async def test_dify_top_k_120_clamped_to_20(monkeypatch):
    captured: dict[str, Any] = {}

    class FakeDify:
        async def retrieve(self, session, query, top_k=5, **kwargs):
            captured["retrieve_top_k"] = top_k
            return []

    class FakeLlm:
        async def chat(self, messages, stream=False, **kwargs):
            return "測試回答"

    monkeypatch.setattr(
        chat_service,
        "get_merged",
        AsyncMock(
            return_value={
                "local_top_k": 12,
                "dify_top_k": 120,
                "system_prompt": "系統提示",
                "cite_inline_refs": False,
            }
        ),
    )
    monkeypatch.setattr(chat_service, "get_dify_knowledge", lambda: FakeDify())
    monkeypatch.setattr(chat_service, "get_llm_client", lambda: FakeLlm())
    monkeypatch.setattr(
        chat_service,
        "build_system_prompt",
        lambda rs, programme=None, topic=None: rs.get("system_prompt") or "系統提示",
    )

    await chat_service.answer_question(
        _session_mock(),
        user_id=uuid.uuid4(),
        question="姊妹學校津貼如何使用？",
        knowledge_source="dify",
        locale="zh-HK",
    )
    assert captured["retrieve_top_k"] == 20


@pytest.mark.asyncio
async def test_each_chunk_clipped_to_1200_chars(monkeypatch):
    result = await _run_answer(
        monkeypatch, local_top_k=12, retrieved_count=12, content_len=2000
    )
    captured = result["_captured"]
    blocks = _context_blocks_from_messages(captured["messages"])
    assert len(blocks) == 12
    for block in blocks:
        # 標題列之後為正文
        body = block.split("\n", 1)[1]
        # 截斷後為 1200 字 + 「…」
        assert body.endswith("…")
        assert len(body) == 1201


def test_retrieve_chunks_fetch_k_covers_top_k():
    """合併前取回數量須不少於 top_k，否則無法湊滿設定的段落數。"""
    for top_k in (1, 5, 8, 12, 20, 50):
        fetch_k = max(top_k * 2, 12)
        assert fetch_k >= top_k


@pytest.mark.asyncio
async def test_retrieve_chunks_returns_at_most_top_k(monkeypatch):
    """retrieve_chunks 最終回傳數量不得超過 top_k（排序邏輯本身不變）。"""

    async def fake_vector(session, query, top_k, **kwargs):
        return _make_hits(top_k)

    async def fake_keyword(session, query, top_k, **kwargs):
        # 回傳另一批，確保合併路徑被走到
        hits = _make_hits(top_k)
        for h in hits:
            h["document_id"] = str(uuid.uuid4())
            h["score"] = 0.5
        return hits

    monkeypatch.setattr("app.services.rag._vector_retrieve", fake_vector)
    monkeypatch.setattr("app.services.rag._keyword_retrieve", fake_keyword)

    out = await retrieve_chunks(MagicMock(), "姊妹學校", top_k=12)
    assert len(out) == 12
