from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.sources import get_sources_config, put_sources_config, suggest_sources_api


def _site():
    return {
        "id": "edb_example",
        "name": {"en": "Example", "zh-HK": "例子"},
        "enabled": False,
        "priority": 1,
        "type": "site_attachments",
        "base_url": "https://www.edb.gov.hk/tc/example",
        "allow_hosts": ["www.edb.gov.hk"],
        "file_extensions": [".pdf"],
        "rate_limit_seconds": 1.5,
        "schedule": "0 7 * * 0",
        "max_pages": 200,
    }


@pytest.mark.asyncio
async def test_put_saves_and_syncs(tmp_path: Path, monkeypatch):
    path = tmp_path / "sources.yaml"
    monkeypatch.setattr("app.api.sources.sources_file_path", lambda: path)
    synced = AsyncMock()
    monkeypatch.setattr("app.api.sources.sync_sources_table", synced)
    body = type("Body", (), {"sources": [_site()]})()
    result = await put_sources_config(body, session=AsyncMock(), user=AsyncMock())
    assert result["sources"][0]["id"] == "edb_example"
    assert path.exists()
    synced.assert_awaited()


@pytest.mark.asyncio
async def test_get_invalid_file_is_422(tmp_path: Path, monkeypatch):
    path = tmp_path / "sources.yaml"
    path.write_text(":", encoding="utf-8")
    monkeypatch.setattr("app.api.sources.sources_file_path", lambda: path)
    with pytest.raises(HTTPException) as exc:
        await get_sources_config(user=AsyncMock())
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_suggest_missing_key_is_400(monkeypatch):
    monkeypatch.setattr(
        "app.api.sources.resolved_settings",
        lambda: {"jina_api_key": ""},
    )
    body = type("Body", (), {"mode": "topic", "query": "課程"})()
    with pytest.raises(HTTPException) as exc:
        await suggest_sources_api(body, user=AsyncMock())
    assert exc.value.status_code == 400
