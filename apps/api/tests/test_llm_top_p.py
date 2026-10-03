"""驗證 llm_top_p：留空不傳送；有值時 OpenRouter／Ollama 才帶 top_p。"""

from unittest.mock import AsyncMock

import pytest

from app.services.llm import OllamaClient, OpenRouterClient, optional_top_p

_OPENROUTER_RS = {
    "openrouter_api_key": "sk-test",
    "openrouter_model": "test-model",
    "openrouter_base_url": "https://openrouter.ai/api/v1",
    "app_name": "test",
    "temperature": 0.2,
    "max_tokens": 4096,
    "llm_top_p": None,
}

_OLLAMA_RS = {
    "ollama_base_url": "http://localhost:11434",
    "ollama_model": "test-ollama",
    "temperature": 0.2,
    "max_tokens": 512,
    "llm_top_p": None,
}


def test_optional_top_p_unset():
    assert optional_top_p({"llm_top_p": None}) is None
    assert optional_top_p({}) is None


def test_optional_top_p_set():
    assert optional_top_p({"llm_top_p": 0.9}) == 0.9
    assert optional_top_p({"llm_top_p": 0}) == 0.0
    assert optional_top_p({"llm_top_p": 1}) == 1.0


def _fake_openrouter_client(seen: dict):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
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
            seen["payload"] = json
            return FakeResp()

    return FakeClient


def _fake_ollama_client(seen: dict):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "ok"}, "done_reason": "stop"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None):
            seen["payload"] = json
            return FakeResp()

    return FakeClient


@pytest.mark.asyncio
async def test_openrouter_omits_top_p_when_unset(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr("app.services.llm.resolved_settings", lambda: dict(_OPENROUTER_RS))
    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", _fake_openrouter_client(seen))
    monkeypatch.setattr("app.services.llm.record_usage", AsyncMock())

    await OpenRouterClient().chat_with_meta(
        [{"role": "user", "content": "hi"}],
        apply_top_p=True,
    )
    assert "top_p" not in seen["payload"]


@pytest.mark.asyncio
async def test_openrouter_includes_top_p_when_set(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(
        "app.services.llm.resolved_settings",
        lambda: {**_OPENROUTER_RS, "llm_top_p": 0.9},
    )
    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", _fake_openrouter_client(seen))
    monkeypatch.setattr("app.services.llm.record_usage", AsyncMock())

    await OpenRouterClient().chat_with_meta(
        [{"role": "user", "content": "hi"}],
        apply_top_p=True,
    )
    assert seen["payload"]["top_p"] == 0.9


@pytest.mark.asyncio
async def test_openrouter_omits_top_p_when_apply_flag_false(monkeypatch):
    """非問答路徑預設不帶 top_p，即使設定值存在。"""
    seen: dict = {}
    monkeypatch.setattr(
        "app.services.llm.resolved_settings",
        lambda: {**_OPENROUTER_RS, "llm_top_p": 0.9},
    )
    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", _fake_openrouter_client(seen))
    monkeypatch.setattr("app.services.llm.record_usage", AsyncMock())

    await OpenRouterClient().chat_with_meta([{"role": "user", "content": "hi"}])
    assert "top_p" not in seen["payload"]


@pytest.mark.asyncio
async def test_ollama_omits_top_p_when_unset(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr("app.services.llm.resolved_settings", lambda: dict(_OLLAMA_RS))
    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", _fake_ollama_client(seen))
    monkeypatch.setattr("app.services.llm.record_usage", AsyncMock())

    await OllamaClient().chat_with_meta(
        [{"role": "user", "content": "hi"}],
        apply_top_p=True,
    )
    assert "top_p" not in seen["payload"]["options"]


@pytest.mark.asyncio
async def test_ollama_includes_top_p_when_set(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(
        "app.services.llm.resolved_settings",
        lambda: {**_OLLAMA_RS, "llm_top_p": 0.5},
    )
    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", _fake_ollama_client(seen))
    monkeypatch.setattr("app.services.llm.record_usage", AsyncMock())

    await OllamaClient().chat_with_meta(
        [{"role": "user", "content": "hi"}],
        apply_top_p=True,
    )
    assert seen["payload"]["options"]["top_p"] == 0.5
