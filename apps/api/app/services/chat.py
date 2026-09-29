from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ChatMessage, ChatSession
from app.services.ingest import extract_text_from_pdf, sanitize_text
from app.services.knowledge import get_dify_knowledge, get_local_knowledge
from app.services.llm import get_llm_client
from app.services.runtime_settings import build_system_prompt, get_merged
from app.services.usage import usage_scope

KnowledgeSource = Literal["local", "local_and_dify", "dify"]

PROMPT_ONLY_USER_MESSAGE = (
    "The user did not enter a question. Respond using only the system prompt "
    "(and any programme/topic filter scope in it). Do not claim you searched the "
    "document database. Briefly explain how you can help within that scope and "
    "invite a specific question (e.g. a circular number or keyword)."
)
PROMPT_ONLY_STORED = "（僅系統提示）"

ALLOWED_UPLOAD_SUFFIXES = {".pdf", ".txt", ".md", ".csv"}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_ATTACHMENTS = 3
MAX_ATTACHMENT_CHARS = 12_000
MAX_HISTORY_MESSAGES = 12
MAX_HISTORY_CHARS = 1_600
MAX_HISTORY_TURN_CHARS = 5_000

_FILENAME_SAFE = re.compile(r"[^\w.\- ()\u4e00-\u9fff]+", re.UNICODE)


def is_prompt_only(question: str) -> bool:
    return not (question or "").strip()


def clip_text(text: str, limit: int) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "…"


def safe_filename(name: str) -> str:
    base = (name or "upload").replace("\\", "/").split("/")[-1].strip()
    base = _FILENAME_SAFE.sub("_", base).strip("._ ")
    return (base or "upload")[:180]


def extract_upload(filename: str, data: bytes) -> dict[str, Any]:
    """Pull plain text from a chat attachment. Raises ValueError with a stable code."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("file_too_large")
    name = safe_filename(filename)
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        raise ValueError("unsupported_type")
    if suffix == ".pdf":
        text = extract_text_from_pdf(data)
    else:
        text = sanitize_text(data.decode("utf-8", errors="replace"))
    text = clip_text(text, MAX_ATTACHMENT_CHARS)
    if not text:
        raise ValueError("no_text")
    return {"filename": name, "text": text, "char_count": len(text)}


def normalize_attachments(raw: list[dict] | None) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for item in raw or []:
        text = clip_text(str(item.get("text") or ""), MAX_ATTACHMENT_CHARS)
        if not text:
            continue
        filename = safe_filename(str(item.get("filename") or "file"))
        cleaned.append({"filename": filename, "text": text, "char_count": len(text)})
        if len(cleaned) >= MAX_ATTACHMENTS:
            break
    return cleaned


def format_user_turn(content: str, attachments: list | None) -> str:
    blocks: list[str] = []
    for att in attachments or []:
        if not isinstance(att, dict):
            continue
        text = clip_text(str(att.get("text") or ""), 4_000)
        name = att.get("filename") or "file"
        if text:
            blocks.append(f"[Attached file: {name}]\n{text}")
    body = (content or "").strip()
    if body and body != PROMPT_ONLY_STORED:
        blocks.append(body)
    elif body and not blocks:
        blocks.append(body)
    return clip_text("\n\n".join(blocks), MAX_HISTORY_TURN_CHARS)


def build_chat_messages(
    *,
    system: str,
    lang_hint: str,
    question: str,
    context_blocks: list[str],
    history: list[dict[str, str]] | None = None,
    attachments: list[dict] | None = None,
) -> list[dict[str, str]]:
    system_content = system + "\n" + lang_hint
    attachment_blocks: list[str] = []
    for att in attachments or []:
        text = (att.get("text") or "").strip()
        if not text:
            continue
        filename = att.get("filename") or "file"
        attachment_blocks.append(f"[Attached file: {filename}]\n{text}")
    attached = "\n\n".join(attachment_blocks)

    if is_prompt_only(question) and not attached:
        current = PROMPT_ONLY_USER_MESSAGE
    else:
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
        if attached and is_prompt_only(question):
            question_line = (
                "The user attached the files below and did not type a separate question. "
                "Summarise the files and relate them to any retrieved circular context."
            )
        else:
            question_line = f"Question: {question}"
        parts = [empty_hint]
        if attached:
            parts.append(
                "The user attached the following files in this turn. Use them together with the "
                f"conversation so far and the retrieved circular context.\n\nAttached files:\n{attached}"
            )
        parts.append(f"Context:\n{context}")
        parts.append(question_line)
        current = "\n\n".join(parts)

    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    for turn in history or []:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        messages.append({"role": role, "content": clip_text(content, MAX_HISTORY_TURN_CHARS)})
    messages.append({"role": "user", "content": current})
    return messages


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def session_summary(chat: ChatSession) -> dict[str, Any]:
    return {
        "id": str(chat.id),
        "title": chat.title,
        "knowledge_source": chat.knowledge_source,
        "created_at": _iso(chat.created_at),
        "updated_at": _iso(chat.updated_at or chat.created_at),
    }


def message_public(msg: ChatMessage) -> dict[str, Any]:
    attachments = []
    for att in msg.attachments or []:
        if not isinstance(att, dict):
            continue
        attachments.append(
            {
                "filename": att.get("filename") or "file",
                "char_count": int(att.get("char_count") or len(att.get("text") or "")),
            }
        )
    return {
        "id": str(msg.id),
        "role": msg.role,
        "content": msg.content,
        "citations": msg.citations or [],
        "attachments": attachments,
        "created_at": _iso(msg.created_at),
    }


async def list_sessions(session: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
            .limit(50)
        )
    ).all()
    return [session_summary(row) for row in rows]


async def get_session_detail(
    session: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID
) -> dict[str, Any] | None:
    chat = await session.get(ChatSession, session_id)
    if not chat or chat.user_id != user_id:
        return None
    messages = (
        await session.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == chat.id)
            .order_by(ChatMessage.created_at.asc())
        )
    ).all()
    detail = session_summary(chat)
    detail["messages"] = [message_public(msg) for msg in messages]
    return detail


async def delete_session(session: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID) -> bool:
    chat = await session.get(ChatSession, session_id)
    if not chat or chat.user_id != user_id:
        return False
    await session.execute(delete(ChatMessage).where(ChatMessage.session_id == chat.id))
    await session.delete(chat)
    await session.commit()
    return True


async def _history_for_llm(session: AsyncSession, chat_id: uuid.UUID) -> list[dict[str, str]]:
    rows = (
        await session.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == chat_id)
            .order_by(ChatMessage.created_at.asc())
        )
    ).all()
    tail = rows[-MAX_HISTORY_MESSAGES:]
    history: list[dict[str, str]] = []
    for row in tail:
        if row.role == "user":
            content = format_user_turn(row.content, row.attachments)
        elif row.role == "assistant":
            content = clip_text(row.content, MAX_HISTORY_CHARS)
        else:
            continue
        if content:
            history.append({"role": row.role, "content": content})
    return history


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
    attachments: list[dict] | None = None,
) -> dict[str, Any]:
    atts = normalize_attachments(attachments)
    prompt_only = is_prompt_only(question) and not atts
    q_display = question.strip() if not is_prompt_only(question) else ""
    retrieve_query = q_display or (atts[0]["text"][:400] if atts else "")

    if session_id:
        chat = await session.get(ChatSession, session_id)
        if not chat or chat.user_id != user_id:
            chat = None
    else:
        chat = None

    if not chat:
        if q_display:
            title = q_display[:80]
        elif atts:
            title = atts[0]["filename"][:80]
        else:
            title = PROMPT_ONLY_STORED
        chat = ChatSession(user_id=user_id, title=title, knowledge_source=knowledge_source)
        session.add(chat)
        await session.flush()
    elif chat.title in ("New chat", PROMPT_ONLY_STORED) and q_display:
        chat.title = q_display[:80]
    chat.knowledge_source = knowledge_source

    history = await _history_for_llm(session, chat.id)

    rs = await get_merged(session)

    local_hits: list[dict] = []
    dify_hits: list[dict] = []
    if retrieve_query:
        if knowledge_source in ("local", "local_and_dify"):
            local_hits = await get_local_knowledge().retrieve(
                session,
                retrieve_query,
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
                session, retrieve_query, top_k=int(rs["dify_top_k"])
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
        history=history,
        attachments=atts,
    )

    llm = get_llm_client()
    with usage_scope("chat"):
        answer = await llm.chat(messages, stream=False)
    assert isinstance(answer, str)

    now = datetime.now(timezone.utc)
    stored_user = q_display or ("" if atts else PROMPT_ONLY_STORED)
    session.add(
        ChatMessage(
            session_id=chat.id,
            role="user",
            content=stored_user,
            attachments=atts or None,
            created_at=now,
        )
    )
    session.add(
        ChatMessage(
            session_id=chat.id,
            role="assistant",
            content=answer,
            citations=citations,
            created_at=now + timedelta(milliseconds=1),
        )
    )
    chat.updated_at = now + timedelta(milliseconds=1)
    await session.commit()

    return {
        "session_id": str(chat.id),
        "answer": answer,
        "citations": citations,
        "knowledge_source": knowledge_source,
        "programme": programme,
        "topic": topic,
        "prompt_only": prompt_only,
        "attachments": [
            {"filename": att["filename"], "char_count": att["char_count"]} for att in atts
        ],
    }
