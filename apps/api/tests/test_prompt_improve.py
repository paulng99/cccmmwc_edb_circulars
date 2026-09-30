from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.schemas import ImproveSystemPromptBody
from app.api.settings import improve_system_prompt_api
from app.services.prompt_improve import improve_system_prompt


def test_improve_body_rejects_empty():
    with pytest.raises(ValidationError):
        ImproveSystemPromptBody(prompt="")


@pytest.mark.asyncio
async def test_improve_system_prompt_strips_and_calls_llm(monkeypatch):
    seen: dict = {}

    class FakeLlm:
        async def chat(self, messages, stream=False, reasoning=True):
            seen["messages"] = messages
            seen["stream"] = stream
            seen["reasoning"] = reasoning
            return "  Improved prompt  "

    monkeypatch.setattr("app.services.prompt_improve.get_llm_client", lambda: FakeLlm())
    result = await improve_system_prompt("  draft rules  ")
    assert result == "Improved prompt"
    assert seen["stream"] is False
    assert seen["reasoning"] is False
    assert seen["messages"][1]["content"] == "draft rules"


@pytest.mark.asyncio
async def test_improve_system_prompt_empty_raises():
    with pytest.raises(ValueError, match="prompt_empty"):
        await improve_system_prompt("   ")


@pytest.mark.asyncio
async def test_improve_api_success(monkeypatch):
    async def fake_improve(draft: str) -> str:
        assert draft == "BASE"
        return "BETTER"

    monkeypatch.setattr("app.api.settings.improve_system_prompt", fake_improve)
    user = MagicMock()
    user.id = "user-1"
    body = ImproveSystemPromptBody(prompt="BASE")
    result = await improve_system_prompt_api(body, user=user)
    assert result == {"prompt": "BETTER"}


@pytest.mark.asyncio
async def test_improve_api_whitespace_only_is_422():
    user = MagicMock()
    user.id = "user-1"
    body = ImproveSystemPromptBody(prompt="  x  ")
    # Body allows "x"; whitespace-only after strip is enforced in the handler.
    # Simulate by calling with a body that strips to empty via monkeypatch of strip path:
    body_ws = ImproveSystemPromptBody.model_construct(prompt="   ")
    with pytest.raises(HTTPException) as exc:
        await improve_system_prompt_api(body_ws, user=user)
    assert exc.value.status_code == 422
    assert exc.value.detail == "prompt_empty"


@pytest.mark.asyncio
async def test_improve_api_llm_failure_is_502(monkeypatch):
    async def boom(draft: str) -> str:
        raise RuntimeError("llm_empty")

    monkeypatch.setattr("app.api.settings.improve_system_prompt", boom)
    user = MagicMock()
    user.id = "user-1"
    with pytest.raises(HTTPException) as exc:
        await improve_system_prompt_api(ImproveSystemPromptBody(prompt="BASE"), user=user)
    assert exc.value.status_code == 502
    assert exc.value.detail == "improve_failed"


@pytest.mark.asyncio
async def test_improve_api_does_not_persist(monkeypatch):
    update = AsyncMock()
    monkeypatch.setattr("app.api.settings.update_settings", update)

    async def fake_improve(draft: str) -> str:
        return "BETTER"

    monkeypatch.setattr("app.api.settings.improve_system_prompt", fake_improve)
    user = MagicMock()
    user.id = "user-1"
    await improve_system_prompt_api(ImproveSystemPromptBody(prompt="BASE"), user=user)
    update.assert_not_called()
