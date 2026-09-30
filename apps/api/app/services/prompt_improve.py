from __future__ import annotations

from app.services.llm import get_llm_client
from app.services.usage import usage_scope

IMPROVE_META = """You improve system prompts for an assistant that answers questions about Hong Kong Education Bureau (EDB) circulars and documents.

Rules:
1. Preserve the author's intent, constraints, and language. If the draft is Chinese, keep Traditional Chinese (zh-HK).
2. Improve clarity, structure, and actionable rules. Prefer numbered rules when helpful.
3. Do not invent product features or policies that are not implied by the draft.
4. Output ONLY the improved system prompt text — no preamble, no markdown fences, no explanation.
"""


async def improve_system_prompt(draft: str) -> str:
    text = draft.strip()
    if not text:
        raise ValueError("prompt_empty")
    llm = get_llm_client()
    with usage_scope("settings_improve"):
        answer = await llm.chat(
            [
                {"role": "system", "content": IMPROVE_META},
                {"role": "user", "content": text},
            ],
            stream=False,
            reasoning=False,
        )
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("llm_empty")
    return answer.strip()
