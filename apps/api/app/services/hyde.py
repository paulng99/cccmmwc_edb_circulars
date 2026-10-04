"""HyDE: hypothetical document embeddings for vector retrieval."""

from __future__ import annotations

import asyncio
import logging
import re

from app.services.llm import get_llm_client
from app.services.usage import usage_scope

logger = logging.getLogger(__name__)

HYDE_TIMEOUT_SECONDS = 8.0
MAX_HYDE_CHARS = 480

HYDE_SYSTEM = """You help retrieve Hong Kong Education Bureau (EDB) circulars and grant documents.

Task: write a short hypothetical passage that could appear inside an official EDB circular or grant-rate notice and would answer the user's question.

Rules:
1. Output ONLY the passage text — no preamble, no markdown, no bullet labels.
2. Prefer Traditional Chinese (zh-HK). Official programme names are OK in Chinese or English acronyms.
3. Include concrete-looking details typical of EDB docs (programme title, school year YYYY/YY, amounts, eligibility) when the question implies them — invent plausible wording for retrieval only.
4. Keep the passage under 400 Chinese characters / ~80 words.
5. This text is NOT shown to the user and is NOT the final answer — it is only used for vector search.
"""


def clip_hyde_passage(text: str, *, max_chars: int = MAX_HYDE_CHARS) -> str:
    """Normalize and cap hypothetical passage length."""
    raw = (text or "").strip()
    if not raw:
        return ""
    fence = re.search(r"```(?:\w+)?\s*(.*?)```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    # Drop common preambles if the model ignores instructions.
    for prefix in ("假設段落：", "假設文件：", "Passage:", "Hypothetical:"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :].strip()
    raw = re.sub(r"\s+", " ", raw).strip()
    if len(raw) > max_chars:
        raw = raw[:max_chars].rstrip()
    return raw


async def generate_hyde_passage(question: str) -> str | None:
    """Generate a short hypothetical EDB passage for embedding. None on failure."""
    q = (question or "").strip()
    if not q:
        return None
    llm = get_llm_client()
    messages = [
        {"role": "system", "content": HYDE_SYSTEM},
        {"role": "user", "content": q},
    ]
    try:
        with usage_scope("hyde"):
            raw = await asyncio.wait_for(
                llm.chat(messages, stream=False, reasoning=False),
                timeout=HYDE_TIMEOUT_SECONDS,
            )
        if not isinstance(raw, str):
            parts: list[str] = []
            async for chunk in raw:  # type: ignore[union-attr]
                parts.append(str(chunk))
            text = "".join(parts)
        else:
            text = raw
        passage = clip_hyde_passage(text)
        return passage or None
    except Exception:
        logger.exception("HyDE passage generation failed; skipping HyDE retrieve")
        return None
