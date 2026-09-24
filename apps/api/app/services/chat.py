from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ChatMessage, ChatSession
from app.services.knowledge import get_dify_knowledge, get_local_knowledge
from app.services.llm import get_llm_client
from app.services.runtime_settings import build_system_prompt, get_merged

KnowledgeSource = Literal["local", "local_and_dify", "dify"]

PROMPT_ONLY_USER_MESSAGE = (
    "The user did not enter a question. Respond using only the system prompt "
    "(and any programme/topic filter scope in it). Do not claim you searched the "
    "document database. Briefly explain how you can help within that scope and "
    "invite a specific question (e.g. a circular number or keyword)."
)


def is_prompt_only(question: str) -> bool:
    return not (question or "").strip()


def build_chat_messages(
    *,
    system: str,
    lang_hint: str,
    question: str,
    context_blocks: list[str],
) -> list[dict[str, str]]:
    system_content = system + "\n" + lang_hint
    if is_prompt_only(question):
        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": PROMPT_ONLY_USER_MESSAGE},
        ]

    context = "\n\n---\n\n".join(context_blocks) if context_blocks else "(No matching documents found.)"
    if not context_blocks:
        empty_hint = (
            "The retrieval returned no documents. Tell the user clearly that no matching circular "
            "was found, and suggest retrying with a circular number (e.g. EDBCM048/2026) or a more "
            "specific keyword."
        )
    else:
        empty_hint = (
            f"Retrieved {len(context_blocks)} context block(s). Use them to answer the question. "
            "If they only partially match, still summarise the useful parts."
        )
    return [
        {"role": "system", "content": system_content},
        {
            "role": "user",
            "content": (
                f"{empty_hint}\n\n"
                f"Context:\n{context}\n\n"
                f"Question: {question}"
            ),
        },
    ]


async def answer_question(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    question: str,
    knowledge_source: KnowledgeSource = "local",
    session_id: uuid.UUID | None = None,
    locale: str = "zh-HK",
    programme: str | None = None,
    topic: str | None = None,
) -> dict[str, Any]:
    prompt_only = is_prompt_only(question)
    q_display = question.strip() if not prompt_only else ""

    if session_id:
        chat = await session.get(ChatSession, session_id)
        if not chat or chat.user_id != user_id:
            chat = None
    else:
        chat = None

    if not chat:
        title = q_display[:80] if q_display else "（僅系統提示）"
        chat = ChatSession(user_id=user_id, title=title, knowledge_source=knowledge_source)
        session.add(chat)
        await session.flush()

    rs = await get_merged(session)

    local_hits: list[dict] = []
    dify_hits: list[dict] = []
    if not prompt_only:
        if knowledge_source in ("local", "local_and_dify"):
            local_hits = await get_local_knowledge().retrieve(
                session,
                q_display,
                top_k=int(rs["local_top_k"]),
                programme=programme,
                topic=topic,
            )
        # Keep prompt lean so OpenRouter stays responsive
        local_hits = local_hits[:8]
        for hit in local_hits:
            content = hit.get("content") or ""
            if len(content) > 1200:
                hit["content"] = content[:1200] + "…"
        if knowledge_source in ("dify", "local_and_dify"):
            dify_hits = await get_dify_knowledge().retrieve(
                session, q_display, top_k=int(rs["dify_top_k"])
            )

    context_blocks: list[str] = []
    citations: list[dict[str, Any]] = []
    for i, hit in enumerate(local_hits, start=1):
        issued = hit.get("issued_at") or "n/a"
        circ = hit.get("circular_no") or "n/a"
        context_blocks.append(
            f"[L{i}] {hit['title']} | {circ} | {issued}\n{hit['content']}"
        )
        citations.append(
            {
                "ref": f"L{i}",
                "document_id": hit["document_id"],
                "title": hit["title"],
                "circular_no": hit.get("circular_no"),
                "issued_at": hit.get("issued_at"),
                "source_url": hit.get("source_url"),
                "score": hit.get("score"),
                "backend": "local",
            }
        )
    for i, hit in enumerate(dify_hits, start=1):
        context_blocks.append(f"[D{i}] {hit.get('title') or 'Dify'}\n{hit.get('content', '')}")
        citations.append(
            {
                "ref": f"D{i}",
                "title": hit.get("title"),
                "score": hit.get("score"),
                "backend": "dify",
            }
        )

    lang_hint = "Respond in Traditional Chinese (Hong Kong)." if locale.startswith("zh") else "Respond in English."
    messages = build_chat_messages(
        system=build_system_prompt(rs, programme=programme, topic=topic),
        lang_hint=lang_hint,
        question=q_display,
        context_blocks=context_blocks,
    )

    llm = get_llm_client()
    answer = await llm.chat(messages, stream=False)
    assert isinstance(answer, str)

    session.add(ChatMessage(session_id=chat.id, role="user", content=q_display or "（僅系統提示）"))
    session.add(
        ChatMessage(session_id=chat.id, role="assistant", content=answer, citations=citations)
    )
    await session.commit()

    return {
        "session_id": str(chat.id),
        "answer": answer,
        "citations": citations,
        "knowledge_source": knowledge_source,
        "programme": programme,
        "topic": topic,
        "prompt_only": prompt_only,
    }
