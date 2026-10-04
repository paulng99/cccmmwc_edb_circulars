from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ChatMessage, ChatSession
from app.services.hyde import generate_hyde_passage
from app.services.ingest import extract_text_from_pdf, sanitize_text
from app.services.knowledge import get_dify_knowledge, get_local_knowledge
from app.services.llm import get_llm_client, is_length_truncated
from app.services.query_rewrite import (
    build_dual_queries,
    merge_multi_query_hits,
    rewrite_retrieve_query,
)
from app.services.rag import retrieve_vector_only
from app.services.rerank import rerank_hits
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
MAX_RETRIEVE_QUERY_CHARS = 400
MAX_RETRIEVE_HISTORY_TURNS = 2
MAX_RETRIEVE_HISTORY_TURN_CHARS = 160

_FILENAME_SAFE = re.compile(r"[^\w.\- ()\u4e00-\u9fff]+", re.UNICODE)
# Cues that a standalone question already carries enough retrieval topic.
_RETRIEVE_TOPIC_CUE_RE = re.compile(
    r"(?:20\d{2}\s*[/\-]\s*\d{2}|EDBC[M]?\s*\d+|通告|"
    r"津貼|撥款|資助|姊妹學校|全方位學習|校本|課後|幼稚園|直資)",
    re.IGNORECASE,
)


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
        "truncated": bool(msg.truncated) if msg.truncated is not None else False,
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


def _user_turns_for_retrieve(history: list[dict[str, str]] | None) -> list[str]:
    turns: list[str] = []
    for msg in history or []:
        if msg.get("role") != "user":
            continue
        content = (msg.get("content") or "").strip()
        if not content or content == PROMPT_ONLY_STORED:
            continue
        turns.append(content)
    return turns


def needs_history_for_retrieve(question: str) -> bool:
    """True when the latest question is too thin for standalone retrieval.

    Short follow-ups like「中學每名學生幾多錢？」lack programme/year cues and must
    borrow topic from prior user turns. Questions that already name a grant, academic
    year, or circular stay as-is so we do not dilute a precise query with history.
    """
    q = (question or "").strip()
    if not q:
        return False
    if _RETRIEVE_TOPIC_CUE_RE.search(q) is not None:
        return False
    # No programme/year/circular cues: expand whenever history exists (caller checks).
    return True


def build_retrieve_query(
    question: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Build the RAG query; expand short follow-ups with recent user topic turns."""
    q = (question or "").strip()
    if not q:
        return ""
    prior = _user_turns_for_retrieve(history)
    if not prior or not needs_history_for_retrieve(q):
        return clip_text(q, MAX_RETRIEVE_QUERY_CHARS)

    topic_parts: list[str] = []
    for turn in prior[-MAX_RETRIEVE_HISTORY_TURNS:]:
        snippet = clip_text(turn, MAX_RETRIEVE_HISTORY_TURN_CHARS).rstrip("…").strip()
        if snippet:
            topic_parts.append(snippet)
    if not topic_parts:
        return clip_text(q, MAX_RETRIEVE_QUERY_CHARS)
    combined = " ".join(topic_parts) + "\n" + q
    return clip_text(combined, MAX_RETRIEVE_QUERY_CHARS)


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
    base_retrieve = q_display or (atts[0]["text"][:400] if atts else "")

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
    retrieve_query = (
        build_retrieve_query(base_retrieve, history) if base_retrieve else ""
    )

    rs = await get_merged(session)

    # LLM rewrite → dual-query merge → HyDE vector merge → rerank.
    # Fallback: original retrieve_query; HyDE failure skips that path only.
    search_queries: list[str] = []
    hyde_source_query = retrieve_query
    if retrieve_query:
        rewritten = await rewrite_retrieve_query(retrieve_query)
        search_queries = build_dual_queries(retrieve_query, rewritten)
        if search_queries:
            retrieve_query = search_queries[0]

    local_hits: list[dict] = []
    dify_hits: list[dict] = []
    if search_queries:
        if knowledge_source in ("local", "local_and_dify"):
            # 實際交給 AI 的段落數依設定 local_top_k（預設 10）。
            # 夾住 1–20，避免資料庫舊值（例如 120）直接傳入檢索。
            final_k = min(max(int(rs["local_top_k"]), 1), 20)
            # Wider candidate pool for multi-query merge + rerank.
            pool_k = min(final_k * 2, 40)
            local_backend = get_local_knowledge()
            # Start HyDE generation while dual-query hybrid retrieves run.
            hyde_task = asyncio.create_task(
                generate_hyde_passage(hyde_source_query or q_display)
            )
            hit_lists: list[list[dict]] = []
            for q in search_queries:
                hits = await local_backend.retrieve(
                    session,
                    q,
                    top_k=pool_k,
                    programme=programme,
                    topic=topic,
                )
                hit_lists.append(hits)
            merged = merge_multi_query_hits(hit_lists, top_k=pool_k)
            try:
                hyde_passage = await hyde_task
            except Exception:
                hyde_passage = None
            if hyde_passage:
                hyde_hits = await retrieve_vector_only(
                    session,
                    hyde_passage,
                    pool_k,
                    programme=programme,
                    topic=topic,
                    match="hyde",
                )
                if hyde_hits:
                    merged = merge_multi_query_hits(
                        [merged, hyde_hits], top_k=pool_k
                    )
            rerank_query = q_display or retrieve_query
            local_hits = await rerank_hits(rerank_query, merged, top_n=final_k)
        # 每段內容上限維持 1200 字，避免單段過長佔用上下文。
        for hit in local_hits:
            content = hit.get("content") or ""
            if len(content) > 1200:
                hit["content"] = content[:1200] + "…"
        if knowledge_source in ("dify", "local_and_dify"):
            dify_hits = await get_dify_knowledge().retrieve(
                session,
                retrieve_query,
                top_k=min(max(int(rs["dify_top_k"]), 1), 20),
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
                "chunk_index": hit.get("chunk_index"),
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
        # Prefer chat_with_meta so finish_reason=length can surface a continue UI.
        chat_with_meta = getattr(llm, "chat_with_meta", None)
        if callable(chat_with_meta):
            completion = await chat_with_meta(messages, stream=False, apply_top_p=True)
            answer = completion.content
            truncated = is_length_truncated(completion.finish_reason)
        else:
            answer = await llm.chat(messages, stream=False, apply_top_p=True)
            assert isinstance(answer, str)
            truncated = False

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
            truncated=truncated,
            created_at=now + timedelta(milliseconds=1),
        )
    )
    chat.updated_at = now + timedelta(milliseconds=1)
    await session.commit()

    return {
        "session_id": str(chat.id),
        "answer": answer,
        "citations": citations,
        "truncated": truncated,
        "knowledge_source": knowledge_source,
        "programme": programme,
        "topic": topic,
        "prompt_only": prompt_only,
        "attachments": [
            {"filename": att["filename"], "char_count": att["char_count"]} for att in atts
        ],
    }
