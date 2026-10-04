"""Unit tests for structured retrieve-query rewrite and dual-query merge."""

from __future__ import annotations

import pytest

from app.services.query_rewrite import (
    RewriteResult,
    build_dual_queries,
    merge_multi_query_hits,
    parse_rewrite_payload,
    rewrite_retrieve_query,
)


def test_parse_rewrite_payload_full_json():
    raw = """
    {
      "programme_names": ["全方位學習及姊妹學校津貼", "LWLSSG"],
      "circular_nos": [],
      "school_years": ["2026/27"],
      "synonyms": ["學生資助", "津貼額"],
      "search_queries": [
        "LWLSSG 全方位學習及姊妹學校津貼 2026/27 津貼額",
        "全方位學習及姊妹學校津貼 學生資助"
      ]
    }
    """
    result = parse_rewrite_payload(raw)
    assert result.programme_names[0] == "全方位學習及姊妹學校津貼"
    assert result.school_years == ["2026/27"]
    assert "津貼額" in result.synonyms
    assert len(result.search_queries) == 2
    assert "LWLSSG" in result.search_queries[0]


def test_parse_rewrite_payload_fenced_and_search_query_compat():
    raw = """```json
    {"programme_names": ["姊妹學校"], "search_query": "姊妹學校津貼 申請"}
    ```"""
    result = parse_rewrite_payload(raw)
    assert result.search_queries == ["姊妹學校津貼 申請"]


def test_parse_rewrite_payload_composes_from_fields_when_queries_missing():
    raw = '{"programme_names": ["LWLSSG"], "school_years": ["2026/27"], "synonyms": ["津貼額"]}'
    result = parse_rewrite_payload(raw)
    assert "LWLSSG" in result.search_queries[0]
    assert "2026/27" in result.search_queries[0]
    assert "津貼額" in result.search_queries[0]


def test_parse_rewrite_payload_rejects_empty():
    with pytest.raises(ValueError):
        parse_rewrite_payload("not json")
    with pytest.raises(ValueError):
        parse_rewrite_payload('{"programme_names": []}')


def test_build_dual_queries_prefers_rewrite_then_original():
    rewritten = RewriteResult(
        search_queries=["全方位學習及姊妹學校津貼 津貼額", "LWLSSG grant rates"]
    )
    out = build_dual_queries("LWLSSG 的學生資助", rewritten)
    assert out == [
        "全方位學習及姊妹學校津貼 津貼額",
        "LWLSSG grant rates",
    ]


def test_build_dual_queries_adds_original_when_only_one_rewrite():
    rewritten = RewriteResult(search_queries=["全方位學習及姊妹學校津貼 津貼額"])
    out = build_dual_queries("LWLSSG 的學生資助", rewritten)
    assert out == ["全方位學習及姊妹學校津貼 津貼額", "LWLSSG 的學生資助"]


def test_build_dual_queries_fallback_without_rewrite():
    assert build_dual_queries("原問題", None) == ["原問題"]
    assert build_dual_queries("原問題", RewriteResult()) == ["原問題"]


def test_merge_multi_query_hits_max_and_boost():
    a = [
        {"document_id": "d1", "chunk_index": 0, "score": 0.5, "title": "A"},
        {"document_id": "d2", "chunk_index": 0, "score": 0.4, "title": "B"},
    ]
    b = [
        {"document_id": "d1", "chunk_index": 0, "score": 0.7, "title": "A"},
        {"document_id": "d3", "chunk_index": 1, "score": 0.6, "title": "C"},
    ]
    merged = merge_multi_query_hits([a, b], top_k=3)
    assert [h["document_id"] for h in merged] == ["d1", "d3", "d2"]
    # max(0.5, 0.7) + both_boost 0.12
    assert merged[0]["score"] == pytest.approx(0.82)
    assert merged[0]["match"] == "multi_query"


def test_merge_multi_query_hits_caps_top_k():
    hits = [
        [{"document_id": f"d{i}", "chunk_index": 0, "score": 1.0 - i * 0.01}]
        for i in range(5)
    ]
    flat_lists = [[h[0] for h in hits[:3]], [h[0] for h in hits[2:]]]
    merged = merge_multi_query_hits(flat_lists, top_k=2)
    assert len(merged) == 2


@pytest.mark.asyncio
async def test_rewrite_retrieve_query_timeout_falls_back(monkeypatch):
    class FakeLlm:
        async def chat(self, messages, stream=False, **kwargs):
            import asyncio

            await asyncio.sleep(60)
            return "{}"

    monkeypatch.setattr("app.services.query_rewrite.get_llm_client", lambda: FakeLlm())
    monkeypatch.setattr("app.services.query_rewrite.REWRITE_TIMEOUT_SECONDS", 0.01)
    assert await rewrite_retrieve_query("LWLSSG 津貼") is None


@pytest.mark.asyncio
async def test_rewrite_retrieve_query_parses_llm_json(monkeypatch):
    class FakeLlm:
        async def chat(self, messages, stream=False, **kwargs):
            return (
                '{"programme_names":["全方位學習及姊妹學校津貼"],'
                '"search_queries":["全方位學習及姊妹學校津貼 津貼額"]}'
            )

    monkeypatch.setattr("app.services.query_rewrite.get_llm_client", lambda: FakeLlm())
    result = await rewrite_retrieve_query("LWLSSG 的學生資助")
    assert result is not None
    assert result.search_queries[0] == "全方位學習及姊妹學校津貼 津貼額"
