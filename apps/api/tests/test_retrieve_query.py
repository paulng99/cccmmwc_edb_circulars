"""Follow-up retrieve_query assembly: short questions keep conversation topic."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import chat as chat_service
from app.services.chat import (
    MAX_RETRIEVE_QUERY_CHARS,
    build_retrieve_query,
    needs_history_for_retrieve,
)


def test_needs_history_for_short_follow_up():
    assert needs_history_for_retrieve("中學每名學生幾多錢？") is True
    assert needs_history_for_retrieve("中學") is True
    assert needs_history_for_retrieve("截止日期係幾時？") is True


def test_needs_history_false_when_question_has_topic_cues():
    assert (
        needs_history_for_retrieve("全方位學習及姊妹學校津貼2026/27學年津貼額是多少？")
        is False
    )
    assert needs_history_for_retrieve("EDBCM093/2026 託管服務是什麼？") is False
    assert needs_history_for_retrieve("姊妹學校津貼點用？") is False


def test_build_retrieve_query_expands_short_follow_up_with_prior_user_turns():
    history = [
        {
            "role": "user",
            "content": "全方位學習及姊妹學校津貼2026/27學年津貼額是多少？",
        },
        {"role": "assistant", "content": "小學 $990，中學 $1,350。"},
        {"role": "user", "content": "中學每名學生幾多錢？"},
    ]
    # Current question only (history is prior turns excluding current).
    q = build_retrieve_query(
        "中學每名學生幾多錢？",
        history[:-1],
    )
    assert "全方位學習及姊妹學校津貼" in q
    assert "2026/27" in q
    assert "中學每名學生幾多錢？" in q
    assert len(q) <= MAX_RETRIEVE_QUERY_CHARS


def test_build_retrieve_query_keeps_specific_question_unchanged():
    history = [
        {"role": "user", "content": "先前問過姊妹學校"},
        {"role": "assistant", "content": "ok"},
    ]
    q = "全方位學習津貼 2026/27 的學生資助"
    assert build_retrieve_query(q, history) == q


def test_build_retrieve_query_no_history_returns_question():
    assert build_retrieve_query("中學每名學生幾多錢？", []) == "中學每名學生幾多錢？"


def test_build_retrieve_query_clips_to_max_chars():
    prior = "甲" * 500
    history = [{"role": "user", "content": prior}]
    q = build_retrieve_query("中學？", history)
    assert len(q) <= MAX_RETRIEVE_QUERY_CHARS
    assert q.endswith("中學？") or "中學？" in q


@pytest.mark.asyncio
async def test_answer_question_uses_history_in_retrieve_query(monkeypatch):
    captured: dict[str, Any] = {}
    user_id = uuid.uuid4()
    chat_id = uuid.uuid4()

    class FakeChat:
        def __init__(self):
            self.id = chat_id
            self.user_id = user_id
            self.title = "全方位學習及姊妹學校津貼2026/27"
            self.knowledge_source = "local"
            self.updated_at = None

    class FakeLocal:
        async def retrieve(self, session, query, top_k=8, **kwargs):
            captured["query"] = query
            captured["top_k"] = top_k
            return []

    class FakeLlm:
        async def chat(self, messages, stream=False, **kwargs):
            return "測試回答"

    session = MagicMock()
    session.get = AsyncMock(return_value=FakeChat())
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    monkeypatch.setattr(
        chat_service,
        "_history_for_llm",
        AsyncMock(
            return_value=[
                {
                    "role": "user",
                    "content": "全方位學習及姊妹學校津貼2026/27學年津貼額是多少？",
                },
                {"role": "assistant", "content": "小學 $990，中學 $1,350。"},
            ]
        ),
    )
    monkeypatch.setattr(
        chat_service,
        "get_merged",
        AsyncMock(
            return_value={
                "local_top_k": 10,
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
        "rewrite_retrieve_query",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        chat_service,
        "build_system_prompt",
        lambda rs, programme=None, topic=None: "系統提示",
    )

    await chat_service.answer_question(
        session,
        user_id=user_id,
        question="中學每名學生幾多錢？",
        knowledge_source="local",
        session_id=chat_id,
        locale="zh-HK",
    )
    assert "全方位學習及姊妹學校津貼" in captured["query"]
    assert "中學每名學生幾多錢？" in captured["query"]
