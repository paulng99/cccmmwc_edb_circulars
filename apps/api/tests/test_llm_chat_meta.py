from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from tenacity import wait_none

from app.services.llm import (
    MAX_COMPLETION_TOKENS,
    OpenRouterClient,
    clamp_max_tokens,
    is_length_truncated,
)

_OPENROUTER_RS = {
    "openrouter_api_key": "sk-test",
    "openrouter_model": "test-model",
    "openrouter_base_url": "https://openrouter.ai/api/v1",
    "app_name": "test",
    "temperature": 0.2,
    "max_tokens": 4096,
}


def test_clamp_max_tokens_allows_settings_default():
    assert clamp_max_tokens(4096) == 4096


def test_clamp_max_tokens_no_longer_hard_caps_at_2048():
    assert clamp_max_tokens(3000) == 3000
    assert clamp_max_tokens(8192) == 8192


def test_clamp_max_tokens_absolute_ceiling():
    assert clamp_max_tokens(20_000) == MAX_COMPLETION_TOKENS
    assert clamp_max_tokens(0) == 1
    assert clamp_max_tokens(-5) == 1


def test_is_length_truncated():
    assert is_length_truncated("length") is True
    assert is_length_truncated("LENGTH") is True
    assert is_length_truncated("stop") is False
    assert is_length_truncated(None) is False
    assert is_length_truncated("") is False


@pytest.mark.asyncio
async def test_openrouter_payload_uses_clamped_max_tokens(monkeypatch):
    seen: dict = {}

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            seen["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            seen["url"] = url
            seen["payload"] = json
            return FakeResp()

    monkeypatch.setattr("app.services.llm.resolved_settings", lambda: dict(_OPENROUTER_RS))
    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("app.services.llm.record_usage", AsyncMock())

    client = OpenRouterClient()
    result = await client.chat_with_meta(
        [{"role": "user", "content": "hi"}],
        stream=False,
    )
    assert result.content == "ok"
    assert result.finish_reason == "stop"
    assert seen["payload"]["max_tokens"] == 4096
    assert seen["timeout"] == 120.0


@pytest.mark.asyncio
async def test_openrouter_finish_reason_length(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": "partial…"}, "finish_reason": "length"}],
                "usage": {},
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            return FakeResp()

    monkeypatch.setattr(
        "app.services.llm.resolved_settings",
        lambda: {**_OPENROUTER_RS, "max_tokens": 512},
    )
    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("app.services.llm.record_usage", AsyncMock())

    result = await OpenRouterClient().chat_with_meta([{"role": "user", "content": "hi"}])
    assert is_length_truncated(result.finish_reason) is True
    assert result.content == "partial…"


@pytest.mark.asyncio
async def test_chat_with_meta_retries_once_then_succeeds(monkeypatch):
    """Same tenacity policy as chat(): first failure is retried, second attempt returns."""
    attempts = {"n": 0}

    class OkResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": "recovered"}, "finish_reason": "stop"}],
                "usage": {},
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise httpx.ConnectError("simulated network blip")
            return OkResp()

    monkeypatch.setattr("app.services.llm.resolved_settings", lambda: dict(_OPENROUTER_RS))
    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("app.services.llm.record_usage", AsyncMock())
    # Avoid sleeping during the exponential backoff in unit tests.
    OpenRouterClient.chat_with_meta.retry.wait = wait_none()

    result = await OpenRouterClient().chat_with_meta([{"role": "user", "content": "hi"}])
    assert attempts["n"] == 2
    assert result.content == "recovered"
    assert result.finish_reason == "stop"


@pytest.mark.asyncio
async def test_answer_question_sets_truncated_and_chunk_index(monkeypatch):
    from app.services import chat as chat_mod

    class FakeCompletion:
        content = "Answer body [L1]"
        finish_reason = "length"

    class FakeLlm:
        async def chat_with_meta(self, messages, stream=False, reasoning=True, **kwargs):
            return FakeCompletion()

    class FakeLocal:
        async def retrieve(self, session, query, top_k=8, programme=None, topic=None):
            return [
                {
                    "document_id": "doc-1",
                    "title": "通告甲",
                    "circular_no": "EDBCM001/2026",
                    "issued_at": "2026-01-01",
                    "source_url": "https://example.com/a",
                    "score": 0.9,
                    "content": "段落一",
                    "chunk_index": 2,
                }
            ]

    class FakeDify:
        async def retrieve(self, session, query, top_k=8):
            return []

    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    monkeypatch.setattr(chat_mod, "get_llm_client", lambda: FakeLlm())
    monkeypatch.setattr(chat_mod, "get_local_knowledge", lambda: FakeLocal())
    monkeypatch.setattr(chat_mod, "get_dify_knowledge", lambda: FakeDify())
    monkeypatch.setattr(chat_mod, "get_merged", AsyncMock(return_value={
        "local_top_k": 8,
        "dify_top_k": 4,
        "system_prompt": "SYS",
        "cite_inline_refs": True,
    }))
    monkeypatch.setattr(chat_mod, "build_system_prompt", lambda rs, programme=None, topic=None: "SYS")
    monkeypatch.setattr(chat_mod, "_history_for_llm", AsyncMock(return_value=[]))

    class _Scope:
        def __enter__(self):
            return None

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(chat_mod, "usage_scope", lambda *_a, **_k: _Scope())

    import uuid

    result = await chat_mod.answer_question(
        session,
        user_id=uuid.uuid4(),
        question="測試問題",
        knowledge_source="local",
        locale="zh-HK",
    )
    assert result["truncated"] is True
    assert result["citations"][0]["ref"] == "L1"
    assert result["citations"][0]["chunk_index"] == 2
    assert result["answer"] == "Answer body [L1]"

    # Assistant message persisted with truncated=True
    assistant_msgs = [
        call.args[0]
        for call in session.add.call_args_list
        if getattr(call.args[0], "role", None) == "assistant"
    ]
    assert assistant_msgs
    assert assistant_msgs[0].truncated is True
