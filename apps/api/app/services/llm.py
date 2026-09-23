from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.services.runtime_settings import resolved_settings


class LlmClient(Protocol):
    async def chat(self, messages: list[dict[str, str]], stream: bool = False) -> str | AsyncIterator[str]: ...


class OpenRouterClient:
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def chat(self, messages: list[dict[str, str]], stream: bool = False) -> str | AsyncIterator[str]:
        rs = resolved_settings()
        if not rs.get("openrouter_api_key"):
            answer = (
                "[Demo mode: OPENROUTER_API_KEY not set]\n\n"
                "Based on the retrieved Education Bureau materials in context, "
                "please configure OpenRouter to enable live answers."
            )
            if stream:

                async def _gen() -> AsyncIterator[str]:
                    yield answer

                return _gen()
            return answer

        headers = {
            "Authorization": f"Bearer {rs['openrouter_api_key']}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost",
            "X-Title": rs.get("app_name", "EDB Circulars App"),
        }
        payload: dict[str, Any] = {
            "model": rs["openrouter_model"],
            "messages": messages,
            "stream": stream,
            "temperature": float(rs["temperature"]),
            "max_tokens": int(rs["max_tokens"]),
        }
        if stream:
            return self._stream(headers, payload, rs)
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{rs['openrouter_base_url']}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def _stream(self, headers: dict[str, str], payload: dict[str, Any], rs: dict[str, Any]) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{rs['openrouter_base_url']}/chat/completions",
                headers=headers,
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    import json

                    try:
                        obj = json.loads(data)
                        delta = obj["choices"][0]["delta"].get("content")
                        if delta:
                            yield delta
                    except Exception:
                        continue


class OllamaClient:
    async def chat(self, messages: list[dict[str, str]], stream: bool = False) -> str | AsyncIterator[str]:
        rs = resolved_settings()
        payload = {"model": rs["ollama_model"], "messages": messages, "stream": False}
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(f"{rs['ollama_base_url']}/api/chat", json=payload)
            resp.raise_for_status()
            content = resp.json()["message"]["content"]
            if stream:

                async def _gen() -> AsyncIterator[str]:
                    yield content

                return _gen()
            return content


def get_llm_client() -> LlmClient:
    rs = resolved_settings()
    if rs.get("llm_provider") == "ollama":
        return OllamaClient()
    return OpenRouterClient()
