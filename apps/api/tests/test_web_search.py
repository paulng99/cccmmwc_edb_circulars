"""Web fallback search parsing and the no-key short circuit."""

from __future__ import annotations

import json

import pytest

from app.services.web_search import parse_search_results, search_web


def test_parse_search_results_from_jina_data_list():
    payload = {
        "data": [
            {
                "title": "教育局通告",
                "url": "https://www.edb.gov.hk/tc/example",
                "description": "公開網頁摘要",
            },
            {
                "title": "重複",
                "url": "https://www.edb.gov.hk/tc/example",
                "description": "same",
            },
            {"title": "無連結", "description": "skip"},
            {"title": "javascript", "url": "javascript:alert(1)", "description": "skip"},
        ]
    }
    rows = parse_search_results(payload)
    assert len(rows) == 1
    assert rows[0]["title"] == "教育局通告"
    assert rows[0]["url"] == "https://www.edb.gov.hk/tc/example"
    assert rows[0]["content"] == "公開網頁摘要"


def test_parse_search_results_clips_and_falls_back_to_content():
    payload = {"results": [{"title": "A", "url": "https://example.com/a", "content": "字" * 900}]}
    rows = parse_search_results(json.dumps(payload))
    assert rows[0]["content"].endswith("…")
    assert len(rows[0]["content"]) < 900


def test_parse_search_results_single_object_and_empty_snippet():
    payload = {"data": {"title": "單頁", "url": "https://example.com/one"}}
    rows = parse_search_results(payload, limit=1)
    assert rows == [
        {"title": "單頁", "url": "https://example.com/one", "content": "(No snippet returned.)"}
    ]


def test_parse_search_results_rejects_non_json():
    assert parse_search_results("not-json") == []


@pytest.mark.asyncio
async def test_search_web_skips_without_api_key(monkeypatch):
    monkeypatch.setattr("app.services.web_search.resolved_settings", lambda: {"jina_api_key": ""})

    def boom(*_args, **_kwargs):
        raise AssertionError("http client should not be created")

    monkeypatch.setattr("app.services.web_search.httpx.AsyncClient", boom)
    outcome = await search_web("課程更新")
    assert outcome.attempted is False
    assert outcome.results == []


@pytest.mark.asyncio
async def test_search_web_parses_success_and_swallows_http_errors(monkeypatch):
    monkeypatch.setattr("app.services.web_search.resolved_settings", lambda: {"jina_api_key": "secret"})

    class FakeResp:
        text = json.dumps(
            {"data": [{"title": "網頁", "url": "https://www.edb.gov.hk/x", "description": "摘要"}]}
        )
        headers: dict = {}

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers):
            assert "課程" in url or "%" in url
            assert headers["Authorization"] == "Bearer secret"
            assert headers["X-Respond-With"] == "no-content"
            return FakeResp()

    async def _no_usage(_fields):
        return None

    monkeypatch.setattr("app.services.web_search.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("app.services.web_search.record_usage", _no_usage)
    outcome = await search_web("課程更新")
    assert outcome.attempted is True
    assert outcome.results[0]["title"] == "網頁"

    class BoomClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers):
            raise RuntimeError("down")

    monkeypatch.setattr("app.services.web_search.httpx.AsyncClient", BoomClient)
    failed = await search_web("課程更新")
    assert failed.attempted is True
    assert failed.results == []
