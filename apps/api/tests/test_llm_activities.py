"""LLM activity-date extraction (no local regex fallback for display/backfill)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import activity_dates as activity_dates_mod
from app.services import llm_activities as llm_act
from app.services.llm_activities import (
    ACTIVITIES_PARSED_FLAG,
    BACKFILL_STATUS_DONE,
    BACKFILL_STATUS_IN_PROGRESS,
    BACKFILL_STATUS_KEY,
    extract_activities_via_llm,
    parse_llm_activities,
    refresh_activities_llm_only,
)


# Style excerpts resembling public EDBCM wording (synthetic; UR will recheck 140/2026 & 136/2026).
FIXTURE_EDBCM_140_STYLE = """
教育局通函第140/2026號
有關「教師專業發展計劃」

活動名稱：教師專業發展工作坊
活動日期：2026年11月10日
截止報名日期：2026年10月28日
舉行地點：九龍塘教育服務中心

另請學校於2026年12月2日或之前交回參加意向書。
發出日期：2026年9月15日
"""

FIXTURE_EDBCM_136_STYLE = """
教育局通函第136/2026號
學生活動計劃

活動名稱：專題研習比賽
申請期：2026年10月7日至2026年12月2日
活動內容：鼓勵學生參與專題研習
舉行地點：各參加學校

本通告自2026年10月1日起生效。
最後更新日期：2026年9月20日
"""

FIXTURE_MULTI_JSON = (
    "["
    '{"name":"教師專業發展工作坊","starts_at":"2026-11-10","deadline_at":"2026-10-28",'
    '"summary":"教師培訓","location":"九龍塘教育服務中心"},'
    '{"name":"交回參加意向書","starts_at":null,"deadline_at":"2026-12-02",'
    '"summary":null,"location":null}'
    "]"
)


def test_parse_llm_activities_multi_keeps_separate_rows():
    parsed = parse_llm_activities(FIXTURE_MULTI_JSON)
    assert len(parsed) == 2
    assert parsed[0]["name"] == "教師專業發展工作坊"
    assert parsed[0]["starts_at"] == "2026-11-10"
    assert parsed[0]["deadline_at"] == "2026-10-28"
    assert parsed[1]["name"] == "交回參加意向書"
    assert parsed[1]["deadline_at"] == "2026-12-02"
    assert parsed[1]["starts_at"] is None


@pytest.mark.asyncio
async def test_extract_activities_via_llm_success(monkeypatch):
    class FakeLlm:
        async def chat(self, messages, stream=False, reasoning=True, *, apply_top_p=False):
            assert "140/2026" in messages[1]["content"] or "教師專業發展" in messages[1]["content"]
            assert apply_top_p is True
            assert stream is False
            return FIXTURE_MULTI_JSON

    monkeypatch.setattr(llm_act, "get_llm_client", lambda: FakeLlm())
    monkeypatch.setattr(llm_act, "answer_model_configured", lambda: True)
    result = await extract_activities_via_llm(FIXTURE_EDBCM_140_STYLE)
    assert len(result) == 2
    assert result[0]["deadline_at"] == "2026-10-28"


@pytest.mark.asyncio
async def test_extract_activities_via_llm_failure_returns_none(monkeypatch):
    class BadLlm:
        async def chat(self, *a, **k):
            return "not json"

    monkeypatch.setattr(llm_act, "get_llm_client", lambda: BadLlm())
    monkeypatch.setattr(llm_act, "answer_model_configured", lambda: True)
    assert await extract_activities_via_llm(FIXTURE_EDBCM_136_STYLE) is None


@pytest.mark.asyncio
async def test_refresh_llm_only_failure_clears_no_regex_fallback(monkeypatch):
    doc = SimpleNamespace(
        activities=[
            {"name": "本地正則", "starts_at": "2026-01-01", "deadline_at": "2026-01-02"}
        ],
        extra={"activities_parsed": "12"},
    )

    async def fail(_body: str):
        return None

    monkeypatch.setattr(llm_act, "extract_activities_via_llm", fail)
    changed = await refresh_activities_llm_only(doc, FIXTURE_EDBCM_140_STYLE)
    assert changed is True
    assert doc.activities == []
    assert doc.extra["activities_parsed"] == ACTIVITIES_PARSED_FLAG
    # Must not reintroduce regex-shaped local rows.
    assert not any(a.get("name") == "本地正則" for a in doc.activities)


@pytest.mark.asyncio
async def test_refresh_llm_only_success_overwrites(monkeypatch):
    doc = SimpleNamespace(activities=[], extra={})

    async def ok(_body: str):
        return parse_llm_activities(FIXTURE_MULTI_JSON)

    monkeypatch.setattr(llm_act, "extract_activities_via_llm", ok)
    changed = await refresh_activities_llm_only(doc, FIXTURE_EDBCM_140_STYLE)
    assert changed is True
    assert len(doc.activities) == 2
    assert doc.extra["activities_parsed"] == ACTIVITIES_PARSED_FLAG


@pytest.mark.asyncio
async def test_prepare_backfill_clears_stale_and_sets_in_progress(monkeypatch):
    doc = SimpleNamespace(
        id=uuid.uuid4(),
        activities=[{"name": "舊", "deadline_at": "2026-10-01"}],
        extra={"activities_parsed": "12"},
    )
    settings_row = SimpleNamespace(values={"app_name": "x"})

    class FakeSession:
        def __init__(self):
            self.committed = False

        async def get(self, model, key):
            if key == 1:
                return settings_row
            return None

        async def scalars(self, *_a, **_k):
            return MagicMock(all=lambda: [doc])

        async def commit(self):
            self.committed = True

    session = FakeSession()
    # Avoid real SQLAlchemy select execution path — stub helpers used by prepare.
    monkeypatch.setattr(
        activity_dates_mod,
        "_docs_needing_llm_activities",
        AsyncMock(return_value=[doc]),
    )
    monkeypatch.setattr(
        activity_dates_mod,
        "_load_settings_row",
        AsyncMock(return_value=settings_row),
    )

    result = await activity_dates_mod.prepare_llm_activity_backfill(session)
    assert result["cleared"] == 1
    assert doc.activities == []
    assert settings_row.values[BACKFILL_STATUS_KEY] == BACKFILL_STATUS_IN_PROGRESS
    assert session.committed is True


@pytest.mark.asyncio
async def test_run_backfill_marks_done_and_uses_llm(monkeypatch):
    doc = SimpleNamespace(
        id=uuid.uuid4(),
        activities=[],
        extra={"activities_parsed": "12"},
    )
    settings_row = SimpleNamespace(
        values={BACKFILL_STATUS_KEY: BACKFILL_STATUS_IN_PROGRESS}
    )

    async def docs_needing(_session):
        if (doc.extra or {}).get("activities_parsed") == ACTIVITIES_PARSED_FLAG:
            return []
        return [doc]

    monkeypatch.setattr(
        activity_dates_mod,
        "_docs_needing_llm_activities",
        docs_needing,
    )
    monkeypatch.setattr(
        activity_dates_mod,
        "_load_settings_row",
        AsyncMock(return_value=settings_row),
    )
    monkeypatch.setattr(
        activity_dates_mod,
        "_body_for_doc",
        AsyncMock(return_value=FIXTURE_EDBCM_136_STYLE),
    )

    async def fake_refresh(d, body):
        d.activities = [
            {
                "name": "專題研習比賽",
                "starts_at": "2026-10-07",
                "deadline_at": "2026-12-02",
                "summary": "鼓勵學生參與專題研習",
                "location": "各參加學校",
            }
        ]
        d.extra = {**(d.extra or {}), "activities_parsed": ACTIVITIES_PARSED_FLAG}
        return True

    monkeypatch.setattr(activity_dates_mod, "refresh_activities_llm_only", fake_refresh)

    class FakeSession:
        async def commit(self):
            return None

        async def flush(self):
            return None

    out = await activity_dates_mod.backfill_document_activities(FakeSession())
    assert out["checked"] == 1
    assert out["updated"] == 1
    assert doc.activities[0]["deadline_at"] == "2026-12-02"
    assert settings_row.values[BACKFILL_STATUS_KEY] == BACKFILL_STATUS_DONE


@pytest.mark.asyncio
async def test_backfill_throttles_between_documents(monkeypatch):
    docs = [
        SimpleNamespace(id=uuid.uuid4(), activities=[], extra={"activities_parsed": "12"}),
        SimpleNamespace(id=uuid.uuid4(), activities=[], extra={"activities_parsed": "12"}),
    ]
    settings_row = SimpleNamespace(
        values={BACKFILL_STATUS_KEY: BACKFILL_STATUS_IN_PROGRESS}
    )
    sleep_calls: list[float] = []

    async def docs_needing(_session):
        pending = [
            d
            for d in docs
            if (d.extra or {}).get("activities_parsed") != ACTIVITIES_PARSED_FLAG
        ]
        return pending

    async def fake_refresh(d, _body):
        d.extra = {**(d.extra or {}), "activities_parsed": ACTIVITIES_PARSED_FLAG}
        return True

    async def fake_sleep(seconds: float):
        sleep_calls.append(seconds)

    monkeypatch.setattr(activity_dates_mod, "_docs_needing_llm_activities", docs_needing)
    monkeypatch.setattr(
        activity_dates_mod,
        "_load_settings_row",
        AsyncMock(return_value=settings_row),
    )
    monkeypatch.setattr(
        activity_dates_mod,
        "_body_for_doc",
        AsyncMock(return_value=FIXTURE_EDBCM_136_STYLE),
    )
    monkeypatch.setattr(activity_dates_mod, "refresh_activities_llm_only", fake_refresh)
    monkeypatch.setattr(activity_dates_mod.asyncio, "sleep", fake_sleep)

    class FakeSession:
        async def commit(self):
            return None

    out = await activity_dates_mod.backfill_document_activities(FakeSession())
    assert out["checked"] == 2
    assert sleep_calls == [activity_dates_mod.BACKFILL_INTER_DOC_DELAY_SECONDS]


def test_dates_updating_helper():
    assert activity_dates_mod.dates_updating_from_values(
        {BACKFILL_STATUS_KEY: BACKFILL_STATUS_IN_PROGRESS}
    )
    assert not activity_dates_mod.dates_updating_from_values(
        {BACKFILL_STATUS_KEY: BACKFILL_STATUS_DONE}
    )
    assert not activity_dates_mod.dates_updating_from_values({})
