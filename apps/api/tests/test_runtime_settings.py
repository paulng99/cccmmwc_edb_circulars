import pytest

from app.core.config import Settings
from app.services.runtime_settings import (
    DEFAULT_SYSTEM_PROMPT,
    apply_patch,
    defaults_from_env,
    mask_secret,
    merge_values,
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
