# Document PDF Chatbox — Design

**Date:** 2026-10-07  
**Status:** Approved

## Problem

Users viewing a circular PDF at `/[locale]/documents/[id]` cannot ask questions about that document without leaving for the global `/chat` page.

## Goals

- Add a collapsible Ask panel on the document detail page (top-right of the PDF card).
- Answers use the full local knowledge corpus, with the viewed document prioritized.
- Conversations persist as normal `chat_sessions` and appear in `/chat` history.

## Non-goals

- Streaming responses
- OCR / fal.ai for scanned PDFs
- Redesign of the global `/chat` layout
- Overlay / floating chat window on top of the PDF

## Decisions

| Topic | Choice |
|-------|--------|
| Answer scope | Full corpus + prioritize focus document (score boost + reserve 2–3 chunks) |
| UI | Collapsible fixed-width third column; does not overlay PDF |
| Persistence | Existing chat sessions; title prefixed with circular no./title |
| Resume | On open, load latest session with matching `focus_document_id` |

## Architecture

```
Document page Ask toggle
  → DocumentChatPanel
  → POST /api/chat { focus_document_id, session_id?, question, … }
  → answer_question: retrieve → rerank → boost/reserve focus → LLM
  → chat_sessions.focus_document_id + chat_messages
  → visible in /chat session list
```

### Backend

- `ChatRequest.focus_document_id` (optional UUID string).
- `ChatSession.focus_document_id` (nullable UUID FK to documents).
- After corpus retrieve + rerank: explicitly fetch top chunks from the focus document (`retrieve_document_chunks`), merge into the candidate pool, then boost scores and reserve up to 3 focus hits; fill remaining `final_k` from the rest.
- LLM hint: user is viewing this circular; prioritize it; other circulars allowed when relevant.
- New session title: `「{circular_no or title}」{question…}` (truncated to column limit).
- `session_summary` includes `focus_document_id`.

### Frontend

- Preview card: Download + Ask toggle.
- Open → `.detail-grid.has-chat` three columns: PDF | Details | Chat (~360px).
- `DocumentChatPanel`: local state, `chatAsk` / session list+detail, citations, cancel via AbortController.
- Warn if document status ≠ `ready`; chat still allowed (corpus).

## i18n

English and zh-HK strings for Ask toggle, panel chrome, empty/loading/error, and not-ready warning. Dates remain `yyyy-mm-dd`.

## Edge cases

- Invalid `focus_document_id` format → 400 from API validation.
- Unknown document UUID → proceed without focus boost (no hard fail).
- Focus document has no chunks → skip reserve; corpus-only.
- Document not indexed → banner; corpus chat still works.
