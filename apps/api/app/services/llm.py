from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, NamedTuple, Protocol

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.services.runtime_settings import resolved_settings
from app.services.usage import parse_ollama_usage, parse_openrouter_usage, record_usage

# Absolute ceiling for OpenRouter max_tokens (settings page default is 4096).
MAX_COMPLETION_TOKENS = 8192
# Non-stream OpenRouter calls may emit longer answers after the 2048 cap is lifted.
OPENROUTER_TIMEOUT_SECONDS = 120.0


class ChatCompletion(NamedTuple):
    content: str
    finish_reason: str | None = None


def clamp_max_tokens(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = 1
    return min(max(1, n), MAX_COMPLETION_TOKENS)


def is_length_truncated(finish_reason: str | None) -> bool:
    return (finish_reason or "").lower() == "length"


def optional_top_p(rs: dict[str, Any]) -> float | None:
    """Return llm_top_p when set; otherwise None so callers omit top_p entirely."""
    value = rs.get("llm_top_p")
    if value is None:
        return None
    return float(value)


class LlmClient(Protocol):
    async def chat(
        self,
        messages: list[dict[str, str]],
        stream: bool = False,
        reasoning: bool = True,
        *,
        apply_top_p: bool = False,
    ) -> str | AsyncIterator[str]: ...


class OpenRouterClient:
    def _demo_answer(self) -> str:
        return (
            "[Demo mode: OPENROUTER_API_KEY not set]\n\n"
            "Based on the retrieved Education Bureau materials in context, "
            "please configure OpenRouter to enable live answers."
        )

    def _headers_and_payload(
        self,
        messages: list[dict[str, str]],
        *,
        stream: bool,
        reasoning: bool,
        rs: dict[str, Any],
        apply_top_p: bool = False,
    ) -> tuple[dict[str, str], dict[str, Any]]:
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
            "max_tokens": clamp_max_tokens(rs["max_tokens"]),
        }
        if apply_top_p:
            top_p = optional_top_p(rs)
            if top_p is not None:
                payload["top_p"] = top_p
        if not reasoning:
            # Reasoning models spend the token budget before emitting JSON.
            payload["reasoning"] = {"effort": "none"}
        return headers, payload

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4))
    async def chat(
        self,
        messages: list[dict[str, str]],
        stream: bool = False,
        reasoning: bool = True,
        *,
        apply_top_p: bool = False,
    ) -> str | AsyncIterator[str]:
        rs = resolved_settings()
        if not rs.get("openrouter_api_key"):
            answer = self._demo_answer()
            if stream:

                async def _gen() -> AsyncIterator[str]:
                    yield answer

                return _gen()
            return answer

        headers, payload = self._headers_and_payload(
            messages,
            stream=stream,
            reasoning=reasoning,
            rs=rs,
            apply_top_p=apply_top_p,
        )
        if stream:
            return self._stream(headers, payload, rs)
        result = await self._complete(headers, payload, rs)
        return result.content

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4))
    async def chat_with_meta(
        self,
        messages: list[dict[str, str]],
        stream: bool = False,
        reasoning: bool = True,
        *,
        apply_top_p: bool = False,
    ) -> ChatCompletion:
        """Return content plus finish_reason. Non-stream only for answer_question()."""
        del stream  # answer_question always uses non-stream
        rs = resolved_settings()
        if not rs.get("openrouter_api_key"):
            return ChatCompletion(content=self._demo_answer(), finish_reason="stop")

        headers, payload = self._headers_and_payload(
            messages,
            stream=False,
            reasoning=reasoning,
            rs=rs,
            apply_top_p=apply_top_p,
        )
        return await self._complete(headers, payload, rs)

    async def _complete(
        self,
        headers: dict[str, str],
        payload: dict[str, Any],
        rs: dict[str, Any],
    ) -> ChatCompletion:
        async with httpx.AsyncClient(timeout=OPENROUTER_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{rs['openrouter_base_url']}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            choice = (data.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or ""
            finish_reason = choice.get("finish_reason")
            await record_usage(parse_openrouter_usage(data, fallback_model=str(rs["openrouter_model"])))
            return ChatCompletion(content=content, finish_reason=finish_reason)

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
    async def chat(
        self,
        messages: list[dict[str, str]],
        stream: bool = False,
        reasoning: bool = True,
        *,
        apply_top_p: bool = False,
    ) -> str | AsyncIterator[str]:
        del reasoning
        result = await self.chat_with_meta(messages, apply_top_p=apply_top_p)
        if stream:

            async def _gen() -> AsyncIterator[str]:
                yield result.content

            return _gen()
        return result.content

    async def chat_with_meta(
        self,
        messages: list[dict[str, str]],
        stream: bool = False,
        reasoning: bool = True,
        *,
        apply_top_p: bool = False,
    ) -> ChatCompletion:
        del stream, reasoning  # Ollama path is non-stream; num_predict unchanged.
        rs = resolved_settings()
        options: dict[str, Any] = {
            "temperature": float(rs["temperature"]),
            "num_predict": int(rs["max_tokens"]),
        }
        if apply_top_p:
            top_p = optional_top_p(rs)
            if top_p is not None:
                options["top_p"] = top_p
        payload = {
            "model": rs["ollama_model"],
            "messages": messages,
            "stream": False,
            "options": options,
        }
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(f"{rs['ollama_base_url']}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["message"]["content"]
            await record_usage(parse_ollama_usage(data, model=str(rs["ollama_model"])))
            # Ollama uses done_reason; map length stops the same way as OpenRouter.
            done_reason = data.get("done_reason") or data.get("finish_reason")
            return ChatCompletion(content=content, finish_reason=done_reason)


def get_llm_client() -> LlmClient:
    rs = resolved_settings()
    if rs.get("llm_provider") == "ollama":
        return OllamaClient()
    return OpenRouterClient()
