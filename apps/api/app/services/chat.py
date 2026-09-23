from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ChatMessage, ChatSession
from app.services.knowledge import get_dify_knowledge, get_local_knowledge
from app.services.llm import get_llm_client
from app.services.runtime_settings import DEFAULT_SYSTEM_PROMPT, build_system_prompt, get_merged

KnowledgeSource = Literal["local", "local_and_dify", "dify"]




async def answer_question(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    question: str,
    knowledge_source: KnowledgeSource = "local",
    session_id: uuid.UUID | None = None,
    locale: str = "zh-HK",
) -> dict[str, Any]:
    if session_id:
        chat = await session.get(ChatSession, session_id)
        if not chat or chat.user_id != user_id:
            chat = None
    else:
        chat = None

    if not chat:
        chat = ChatSession(user_id=user_id, title=question[:80], knowledge_source=knowledge_source)
        session.add(chat)
        await session.flush()

    rs = await get_merged(session)

    local_hits: list[dict] = []
    dify_hits: list[dict] = []
    if knowledge_source in ("local", "local_and_dify"):
        local_hits = await get_local_knowledge().retrieve(session, question, top_k=int(rs["local_top_k"]))
    if knowledge_source in ("dify", "local_and_dify"):
        dify_hits = await get_dify_knowledge().retrieve(session, question, top_k=int(rs["dify_top_k"]))

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

    context = "\n\n---\n\n".join(context_blocks) if context_blocks else "(No matching documents found.)"
    lang_hint = "Respond in Traditional Chinese (Hong Kong)." if locale.startswith("zh") else "Respond in English."
    messages = [
        {"role": "system", "content": build_system_prompt(rs) + "\n" + lang_hint},
        {
            "role": "user",
            "content": f"Context:\n{context}\n\nQuestion: {question}",
        },
    ]

    llm = get_llm_client()
    answer = await llm.chat(messages, stream=False)
    assert isinstance(answer, str)

    session.add(ChatMessage(session_id=chat.id, role="user", content=question))
    session.add(
        ChatMessage(session_id=chat.id, role="assistant", content=answer, citations=citations)
    )
    await session.commit()

    return {
        "session_id": str(chat.id),
        "answer": answer,
        "citations": citations,
        "knowledge_source": knowledge_source,
    }
