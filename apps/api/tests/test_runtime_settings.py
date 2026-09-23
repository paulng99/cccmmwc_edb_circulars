import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.models import AppSetting
from app.services.runtime_settings import (
    DEFAULT_SYSTEM_PROMPT,
    apply_patch,
    build_settings_response,
    defaults_from_env,
    ensure_seeded,
    get_cached_merged,
    get_merged,
    invalidate_cache,
    mask_secret,
    merge_values,
    update_settings,
)


def test_mask_secret_empty():
    assert mask_secret("") == {"configured": False, "masked": None}
    assert mask_secret(None) == {"configured": False, "masked": None}


def test_mask_secret_short_and_long():
    assert mask_secret("abcd") == {"configured": True, "masked": "••••abcd"}
    assert mask_secret("sk-1234567890")["masked"].endswith("7890")
    assert mask_secret("sk-1234567890")["configured"] is True


def test_defaults_include_new_keys():
    s = Settings(
        openrouter_api_key="secret-key",
        openrouter_model="google/gemini-2.5-flash",
        llm_provider="openrouter",
    )
    d = defaults_from_env(s)
    assert d["temperature"] == 0.2
    assert d["max_tokens"] == 4096
    assert d["local_top_k"] == 8
    assert d["dify_top_k"] == 5
    assert d["cite_inline_refs"] is True
    assert d["system_prompt"] == DEFAULT_SYSTEM_PROMPT
    assert d["openrouter_api_key"] == "secret-key"
    assert d["llm_provider"] == "openrouter"


def test_merge_db_overrides_env():
    env = {"openrouter_model": "a", "temperature": 0.2}
    db = {"openrouter_model": "b"}
    m = merge_values(env, db)
    assert m["openrouter_model"] == "b"
    assert m["temperature"] == 0.2


def test_apply_patch_keeps_empty_secret():
    current = {"openrouter_api_key": "keep-me", "temperature": 0.2}
    new, warnings = apply_patch(current, {"openrouter_api_key": "", "temperature": 0.5})
    assert new["openrouter_api_key"] == "keep-me"
    assert new["temperature"] == 0.5
    assert warnings == []


def test_apply_patch_dim_warns():
    current = {"jina_embedding_dim": 1024}
    new, warnings = apply_patch(current, {"jina_embedding_dim": 768})
    assert new["jina_embedding_dim"] == 768
    assert "reindex_required" in warnings


def test_apply_patch_rejects_unknown():
    with pytest.raises(ValueError):
        apply_patch({"temperature": 0.2}, {"not_a_key": 1})


def test_build_settings_response_masks():
    merged = defaults_from_env(Settings(openrouter_api_key="super-secret-key"))
    payload = build_settings_response(merged, row=None)
    assert payload["editable"]["openrouter_api_key"]["configured"] is True
    assert "super-secret" not in str(payload)
    assert "admin_password" not in str(payload)
    assert payload["readonly"]["jwt_secret"]["configured"] is True


def test_cache_initially_empty():
    invalidate_cache()
    assert get_cached_merged() is None


def test_cache_round_trip():
    invalidate_cache()
    from app.services import runtime_settings

    runtime_settings._cache = {"temperature": 0.5}
    assert get_cached_merged() == {"temperature": 0.5}
    invalidate_cache()
    assert get_cached_merged() is None


@pytest.mark.asyncio
async def test_ensure_seeded_creates_row_when_missing(monkeypatch):
    session = AsyncMock()
    session.get.return_value = None
    monkeypatch.setattr(
        "app.services.runtime_settings.defaults_from_env",
        lambda _s: {"temperature": 0.2},
    )
    row = await ensure_seeded(session)
    assert isinstance(row, AppSetting)
    assert row.id == 1
    assert row.values == {"temperature": 0.2}
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_merged_uses_cache():
    session = AsyncMock()
    from app.services import runtime_settings

    runtime_settings._cache = {"cached": True}
    result = await get_merged(session)
    assert result == {"cached": True}
    session.get.assert_not_called()


@pytest.mark.asyncio
async def test_update_settings_persists_editable_bag_only(monkeypatch):
    session = AsyncMock()
    row = AppSetting(id=1, values={"temperature": 0.2})
    session.get.return_value = row
    monkeypatch.setattr(
        "app.services.runtime_settings.defaults_from_env",
        lambda _s: {"temperature": 0.2, "max_tokens": 4096},
    )

    user_id = uuid.uuid4()
    merged, warnings, updated_row = await update_settings(
        session, {"temperature": 0.7}, user_id
    )
    assert merged["temperature"] == 0.7
    assert updated_row.updated_by == user_id
    assert "temperature" in updated_row.values
    assert "max_tokens" in updated_row.values
    assert set(updated_row.values.keys()).issubset({"temperature", "max_tokens"})
    session.commit.assert_awaited()
