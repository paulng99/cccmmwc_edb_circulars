"""Fixture-based re-analyze tests (synthetic circular bodies, not real EDB text)."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.documents import reanalyze_selected
from app.api.schemas import ReanalyzeBody
from app.services import reanalyze as reanalyze_mod
from app.services.reanalyze import (
    FAIL_KEEP_MESSAGE,
    UNVERIFIED_PREFIX,
    answer_model_configured,
    maybe_auto_ai_analyze,
    parse_llm_activities,
    reanalyze_documents,
    reanalyze_one,
    school_action_from_extra,
    with_unverified_prefix,
)


FIXTURE_BODY = (
    "【測試夾具】學校須於 2026-10-31 前經網上系統交回參加表格，"
    "並委派一名教師出席簡介會。"
)
# Body with no regex-friendly date labels — only the LLM path can populate dates.
FIXTURE_BODY_OBSCURE = (
    "【測試夾具】請學校安排教師參與有關培訓，詳情及限期見附件日程。"
)
FIXTURE_OLD_ACTION = f"{UNVERIFIED_PREFIX}\n舊有撮要：交回表格。"
FIXTURE_NEW_RAW = "學校須於限期前交回參加表格並委派教師出席。"
FIXTURE_LLM_ACTIVITIES_JSON = (
    '[{"name":"教師培訓","starts_at":"2026-11-01","deadline_at":"2026-11-15",'
    '"summary":"請安排教師出席","location":"教育局總部"}]'
)
FIXTURE_LLM_ACTIVITIES = [
    {
        "name": "教師培訓",
        "starts_at": "2026-11-01",
        "deadline_at": "2026-11-15",
        "summary": "請安排教師出席",
        "location": "教育局總部",
    }
]


def test_reanalyze_body_rejects_empty_selection():
    with pytest.raises(ValidationError):
        ReanalyzeBody(document_ids=[])


def test_with_unverified_prefix_adds_once():
    assert with_unverified_prefix("行動一").startswith(UNVERIFIED_PREFIX)
    already = f"{UNVERIFIED_PREFIX}\n行動一"
    assert with_unverified_prefix(already) == already


def test_school_action_from_extra():
    assert school_action_from_extra({"school_action": "  x  "}) == "x"
    assert school_action_from_extra({"school_action": "   "}) is None
    assert school_action_from_extra({}) is None
    assert school_action_from_extra(None) is None


def test_parse_llm_activities_json_array():
    parsed = parse_llm_activities(FIXTURE_LLM_ACTIVITIES_JSON)
    assert parsed == FIXTURE_LLM_ACTIVITIES


def test_parse_llm_activities_fenced_and_filters_bad_dates():
    raw = (
        "```json\n"
        '[{"name":"A","starts_at":"31/10/2026","deadline_at":"2026-10-31",'
        '"summary":null,"location":null},'
        '{"name":"B","starts_at":null,"deadline_at":null,"summary":"無日期","location":null}]\n'
        "```"
    )
    parsed = parse_llm_activities(raw)
    assert len(parsed) == 1
    assert parsed[0]["name"] == "A"
    assert parsed[0]["starts_at"] is None  # bad format dropped
    assert parsed[0]["deadline_at"] == "2026-10-31"


def test_parse_llm_activities_empty_array():
    assert parse_llm_activities("[]") == []


def test_parse_llm_activities_invalid_raises():
    with pytest.raises(ValueError):
        parse_llm_activities("not json")


def test_answer_model_configured_openrouter(monkeypatch):
    monkeypatch.setattr(
        reanalyze_mod,
        "resolved_settings",
        lambda: {"llm_provider": "openrouter", "openrouter_api_key": "sk-test"},
    )
    assert answer_model_configured() is True
    monkeypatch.setattr(
        reanalyze_mod,
        "resolved_settings",
        lambda: {"llm_provider": "openrouter", "openrouter_api_key": ""},
    )
    assert answer_model_configured() is False


def test_answer_model_configured_ollama(monkeypatch):
    monkeypatch.setattr(
        reanalyze_mod,
        "resolved_settings",
        lambda: {"llm_provider": "ollama", "ollama_model": "llama"},
    )
    assert answer_model_configured() is True
    monkeypatch.setattr(
        reanalyze_mod,
        "resolved_settings",
        lambda: {"llm_provider": "ollama", "ollama_model": "  "},
    )
    assert answer_model_configured() is False


def _fake_doc(*, school_action: str | None = FIXTURE_OLD_ACTION) -> SimpleNamespace:
    extra = {"school_action": school_action} if school_action is not None else {}
    return SimpleNamespace(
        id=uuid.uuid4(),
        extra=extra,
        storage_key=None,
        activities=[{"name": "簡介會", "deadline_at": "2026-10-31", "summary": "本地抽取內容"}],
    )


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(self, doc: SimpleNamespace | None):
        self.doc = doc
        self.flushed = False
        self._chunk_rows: list[tuple[str]] = [(FIXTURE_BODY,)]

    async def get(self, _model, doc_id):
        if self.doc is None:
            return None
        if doc_id != self.doc.id:
            return None
        return self.doc

    async def execute(self, _stmt):
        return _FakeResult(self._chunk_rows)

    async def flush(self):
        self.flushed = True


def _is_activities_prompt(messages: list) -> bool:
    system = messages[0]["content"] if messages else ""
    return "activities" in system.lower() or "活動" in system


@pytest.mark.asyncio
async def test_reanalyze_one_success_prefixes_and_uses_llm_activities(monkeypatch):
    doc = _fake_doc()
    db = _FakeDb(doc)
    db._chunk_rows = [(FIXTURE_BODY_OBSCURE,)]
    seen: dict = {"calls": 0, "systems": []}
    old_activities = list(doc.activities)

    class FakeLlm:
        async def chat(self, messages, stream=False, reasoning=True, *, apply_top_p=False):
            seen["calls"] += 1
            seen["stream"] = stream
            seen["reasoning"] = reasoning
            seen["apply_top_p"] = apply_top_p
            seen["systems"].append(messages[0]["content"])
            seen["last_user"] = messages[1]["content"]
            if _is_activities_prompt(messages):
                return FIXTURE_LLM_ACTIVITIES_JSON
            return f"  {FIXTURE_NEW_RAW}  "

    monkeypatch.setattr(reanalyze_mod, "answer_model_configured", lambda: True)
    monkeypatch.setattr(reanalyze_mod, "get_llm_client", lambda: FakeLlm())

    result = await reanalyze_one(db, doc.id)
    assert result["ok"] is True
    assert result["school_action"] == f"{UNVERIFIED_PREFIX}\n{FIXTURE_NEW_RAW}"
    assert doc.extra["school_action"] == result["school_action"]
    assert db.flushed is True
    assert seen["calls"] >= 2
    assert result["activities"] == FIXTURE_LLM_ACTIVITIES
    assert doc.activities == FIXTURE_LLM_ACTIVITIES
    assert doc.activities != old_activities
    assert seen["stream"] is False
    assert seen["reasoning"] is False
    assert seen["apply_top_p"] is True
    assert FIXTURE_BODY_OBSCURE in seen["last_user"]


@pytest.mark.asyncio
async def test_reanalyze_one_failure_keeps_old_action_but_still_updates_llm_activities(
    monkeypatch,
):
    """School-action LLM empty → keep old action; activities LLM can still succeed."""
    doc = _fake_doc()
    db = _FakeDb(doc)
    db._chunk_rows = [(FIXTURE_BODY_OBSCURE,)]
    old_activities = list(doc.activities)

    class SplitLlm:
        async def chat(self, messages, stream=False, reasoning=True, *, apply_top_p=False):
            if _is_activities_prompt(messages):
                return FIXTURE_LLM_ACTIVITIES_JSON
            return "   "

    monkeypatch.setattr(reanalyze_mod, "answer_model_configured", lambda: True)
    monkeypatch.setattr(reanalyze_mod, "get_llm_client", lambda: SplitLlm())

    result = await reanalyze_one(db, doc.id)
    assert result["ok"] is False
    assert result["error"] == "empty"
    assert result["message"] == FAIL_KEEP_MESSAGE
    assert result["school_action"] == FIXTURE_OLD_ACTION
    assert doc.extra["school_action"] == FIXTURE_OLD_ACTION
    assert doc.activities == FIXTURE_LLM_ACTIVITIES
    assert result["activities"] == FIXTURE_LLM_ACTIVITIES
    assert doc.activities != old_activities
    assert db.flushed is True


@pytest.mark.asyncio
async def test_reanalyze_one_activities_llm_fail_falls_back_to_regex(monkeypatch):
    doc = _fake_doc()
    db = _FakeDb(doc)
    old_activities = list(doc.activities)

    class ActionOnlyLlm:
        async def chat(self, messages, stream=False, reasoning=True, *, apply_top_p=False):
            if _is_activities_prompt(messages):
                return "not a json array"
            return FIXTURE_NEW_RAW

    monkeypatch.setattr(reanalyze_mod, "answer_model_configured", lambda: True)
    monkeypatch.setattr(reanalyze_mod, "get_llm_client", lambda: ActionOnlyLlm())

    result = await reanalyze_one(db, doc.id)
    assert result["ok"] is True
    assert result["activities"] == doc.activities
    assert doc.activities != old_activities
    assert any(a.get("deadline_at") == "2026-10-31" for a in doc.activities)


@pytest.mark.asyncio
async def test_reanalyze_one_model_unset_keeps_old(monkeypatch):
    doc = _fake_doc()
    db = _FakeDb(doc)
    monkeypatch.setattr(reanalyze_mod, "answer_model_configured", lambda: False)
    result = await reanalyze_one(db, doc.id)
    assert result["ok"] is False
    assert result["error"] == "model_unset"
    assert result["school_action"] == FIXTURE_OLD_ACTION
    assert result["message"] == FAIL_KEEP_MESSAGE


@pytest.mark.asyncio
async def test_reanalyze_one_timeout_keeps_old(monkeypatch):
    doc = _fake_doc()
    db = _FakeDb(doc)

    async def slow(*_a, **_k):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(reanalyze_mod, "answer_model_configured", lambda: True)
    monkeypatch.setattr(reanalyze_mod, "_call_answer_model", slow)

    result = await reanalyze_one(db, doc.id)
    assert result["ok"] is False
    assert result["error"] == "timeout"
    assert result["school_action"] == FIXTURE_OLD_ACTION
    assert result["message"] == FAIL_KEEP_MESSAGE


@pytest.mark.asyncio
async def test_reanalyze_one_error_keeps_old(monkeypatch):
    doc = _fake_doc()
    db = _FakeDb(doc)

    class BoomLlm:
        async def chat(self, *args, **kwargs):
            raise RuntimeError("provider down")

    monkeypatch.setattr(reanalyze_mod, "answer_model_configured", lambda: True)
    monkeypatch.setattr(reanalyze_mod, "get_llm_client", lambda: BoomLlm())

    result = await reanalyze_one(db, doc.id)
    assert result["ok"] is False
    assert result["error"] == "error"
    assert result["school_action"] == FIXTURE_OLD_ACTION


@pytest.mark.asyncio
async def test_reanalyze_documents_only_selected(monkeypatch):
    called: list[uuid.UUID] = []

    async def fake_one(db, document_id):
        called.append(document_id)
        return {
            "document_id": str(document_id),
            "ok": True,
            "school_action": "未核對\nok",
            "error": None,
            "message": None,
        }

    monkeypatch.setattr(reanalyze_mod, "reanalyze_one", fake_one)
    a, b = uuid.uuid4(), uuid.uuid4()
    results = await reanalyze_documents(MagicMock(), [a, b])
    assert called == [a, b]
    assert len(results) == 2


@pytest.mark.asyncio
async def test_reanalyze_api_rejects_empty_via_handler_contract():
    """Empty selection must not reach the service (Pydantic min_length=1)."""
    with pytest.raises(ValidationError):
        ReanalyzeBody(document_ids=[])


@pytest.mark.asyncio
async def test_reanalyze_api_success_commits(monkeypatch):
    doc_id = uuid.uuid4()

    async def fake_batch(db, ids):
        assert ids == [doc_id]
        return [
            {
                "document_id": str(doc_id),
                "ok": True,
                "school_action": f"{UNVERIFIED_PREFIX}\n{FIXTURE_NEW_RAW}",
                "error": None,
                "message": None,
            }
        ]

    monkeypatch.setattr("app.api.documents.reanalyze_documents", fake_batch)
    db = MagicMock()
    db.commit = AsyncMock()
    user = MagicMock()
    body = ReanalyzeBody(document_ids=[doc_id])
    out = await reanalyze_selected(body, db=db, user=user)
    assert out.results[0].ok is True
    assert out.results[0].school_action.startswith(UNVERIFIED_PREFIX)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reanalyze_api_dedupes_ids(monkeypatch):
    doc_id = uuid.uuid4()
    seen: list = []

    async def fake_batch(db, ids):
        seen.extend(ids)
        return [
            {
                "document_id": str(doc_id),
                "ok": False,
                "school_action": FIXTURE_OLD_ACTION,
                "error": "empty",
                "message": FAIL_KEEP_MESSAGE,
            }
        ]

    monkeypatch.setattr("app.api.documents.reanalyze_documents", fake_batch)
    db = MagicMock()
    db.commit = AsyncMock()
    body = ReanalyzeBody(document_ids=[doc_id, doc_id])
    await reanalyze_selected(body, db=db, user=MagicMock())
    assert seen == [doc_id]


@pytest.mark.asyncio
async def test_maybe_auto_ai_analyze_skips_when_off(monkeypatch):
    monkeypatch.setattr(reanalyze_mod, "resolved_settings", lambda: {"auto_ai_analyze": False})
    called = False

    async def boom(db, doc_id):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(reanalyze_mod, "reanalyze_one", boom)
    ran = await maybe_auto_ai_analyze(AsyncMock(), uuid.uuid4(), has_text=True)
    assert ran is False
    assert called is False


@pytest.mark.asyncio
async def test_maybe_auto_ai_analyze_skips_without_text(monkeypatch):
    monkeypatch.setattr(reanalyze_mod, "resolved_settings", lambda: {"auto_ai_analyze": True})
    called = False

    async def boom(db, doc_id):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(reanalyze_mod, "reanalyze_one", boom)
    ran = await maybe_auto_ai_analyze(AsyncMock(), uuid.uuid4(), has_text=False)
    assert ran is False
    assert called is False


def _session_with_savepoint() -> MagicMock:
    nested = MagicMock()
    nested.__aenter__ = AsyncMock(return_value=None)
    nested.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.begin_nested = MagicMock(return_value=nested)
    return session


@pytest.mark.asyncio
async def test_maybe_auto_ai_analyze_runs_when_on(monkeypatch):
    monkeypatch.setattr(reanalyze_mod, "resolved_settings", lambda: {"auto_ai_analyze": True})
    doc_id = uuid.uuid4()
    seen: dict = {}

    async def fake(db, incoming):
        seen["id"] = incoming
        return {"ok": True}

    monkeypatch.setattr(reanalyze_mod, "reanalyze_one", fake)
    session = _session_with_savepoint()
    ran = await maybe_auto_ai_analyze(session, doc_id, has_text=True)
    assert ran is True
    assert seen["id"] == doc_id
    session.begin_nested.assert_called_once()


@pytest.mark.asyncio
async def test_maybe_auto_ai_analyze_keeps_index_going_on_error(monkeypatch):
    monkeypatch.setattr(reanalyze_mod, "resolved_settings", lambda: {"auto_ai_analyze": True})

    async def boom(db, doc_id):
        raise RuntimeError("llm down")

    monkeypatch.setattr(reanalyze_mod, "reanalyze_one", boom)
    ran = await maybe_auto_ai_analyze(_session_with_savepoint(), uuid.uuid4(), has_text=True)
    assert ran is True


@pytest.mark.asyncio
async def test_index_document_calls_auto_ai_when_text_indexed(monkeypatch):
    from app.services.rag import index_document

    doc_id = uuid.uuid4()
    doc = SimpleNamespace(
        id=doc_id,
        storage_key="k",
        mime_type="text/plain",
        extra={},
        status="stored",
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=doc)
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()

    monkeypatch.setattr("app.services.rag.get_object_bytes", lambda key: b"school must reply")
    monkeypatch.setattr("app.services.rag.apply_document_dates", lambda *a, **k: None)
    monkeypatch.setattr("app.services.rag.apply_document_activities", lambda *a, **k: None)
    monkeypatch.setattr("app.services.rag.chunk_text", lambda text: ["school must reply"])

    class Embedder:
        async def embed(self, batch):
            return [[0.1] for _ in batch]

    monkeypatch.setattr("app.services.rag.get_embedding_backend", lambda: Embedder())

    async def classify(*_a, **_k):
        return None

    monkeypatch.setattr("app.services.classify.apply_classification", classify)

    class Sync:
        async def sync_document(self, *_a, **_k):
            return None

    monkeypatch.setattr("app.services.rag.get_dify_sync", lambda: Sync())

    seen: dict = {}

    async def fake_auto(db, incoming, *, has_text):
        seen["id"] = incoming
        seen["has_text"] = has_text
        return True

    monkeypatch.setattr("app.services.rag.maybe_auto_ai_analyze", fake_auto)

    result = await index_document(session, doc_id)
    assert result["ok"] is True
    assert result["chunks"] == 1
    assert seen == {"id": doc_id, "has_text": True}
    session.flush.assert_awaited()
