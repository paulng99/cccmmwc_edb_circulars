from datetime import date
from decimal import Decimal

import uuid

from app.services.usage import (
    _user_id,
    jina_cost,
    parse_jina_embed_usage,
    parse_jina_reader_usage,
    parse_ollama_usage,
    parse_openrouter_usage,
    resolve_range,
    usage_user_ref,
)


def test_openrouter_uses_provider_cost():
    parsed = parse_openrouter_usage(
        {
            "id": "gen-1",
            "model": "google/gemini-2.5-flash",
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 4,
                "total_tokens": 14,
                "cost": 0.00021,
            },
        },
        fallback_model="fallback",
    )
    assert parsed["provider"] == "openrouter"
    assert parsed["prompt_tokens"] == 10
    assert parsed["completion_tokens"] == 4
    assert parsed["total_tokens"] == 14
    assert parsed["cost_usd"] == Decimal("0.00021")
    assert parsed["cost_source"] == "provider"
    assert parsed["request_id"] == "gen-1"


def test_openrouter_without_cost_is_unknown():
    parsed = parse_openrouter_usage({"usage": {"prompt_tokens": 3, "completion_tokens": 1}}, fallback_model="m")
    assert parsed["total_tokens"] == 4
    assert parsed["cost_usd"] == Decimal(0)
    assert parsed["cost_source"] == "unknown"
    assert parsed["model"] == "m"


def test_jina_embed_estimate_uses_list_rate():
    parsed = parse_jina_embed_usage(
        {"model": "jina-embeddings-v3", "usage": {"total_tokens": 1_000_000, "prompt_tokens": 1_000_000}},
        model="fallback",
    )
    assert parsed["provider"] == "jina"
    assert parsed["total_tokens"] == 1_000_000
    assert parsed["cost_usd"] == Decimal("0.05")
    assert parsed["cost_source"] == "estimate"
    assert jina_cost(0) == (Decimal("0"), "unknown")


def test_jina_reader_reads_nested_usage_or_header():
    body = '{"data":{"usage":{"tokens":2000}}}'
    parsed = parse_jina_reader_usage(body, {})
    assert parsed["total_tokens"] == 2000
    assert parsed["cost_source"] == "estimate"
    assert parsed["model"] == "jina-search"

    missing = parse_jina_reader_usage("not-json", {"x-usage-tokens": "50"})
    assert missing["total_tokens"] == 50


def test_ollama_is_local_zero_cost():
    parsed = parse_ollama_usage({"prompt_eval_count": 8, "eval_count": 12, "message": {"content": "hi"}}, model="qwen")
    assert parsed["provider"] == "ollama"
    assert parsed["total_tokens"] == 20
    assert parsed["cost_usd"] == Decimal(0)
    assert parsed["cost_source"] == "local"


def test_usage_user_ref_binds_and_clears():
    user_id = uuid.uuid4()
    assert _user_id.get() is None
    with usage_user_ref(str(user_id)):
        assert _user_id.get() == user_id
    assert _user_id.get() is None
    with usage_user_ref(None):
        assert _user_id.get() is None
    with usage_user_ref("not-a-uuid"):
        assert _user_id.get() is None


def test_resolve_range_is_inclusive_hong_kong_days(monkeypatch):
    monkeypatch.setattr("app.services.usage.hk_today", lambda: date(2026, 9, 29))
    start, end = resolve_range(days=7, date_from=None, date_to=None)
    assert start.isoformat() == "2026-09-23"
    assert end.isoformat() == "2026-09-29"

    start, end = resolve_range(days=None, date_from=date(2026, 9, 1), date_to=date(2026, 9, 2))
    assert (start, end) == (date(2026, 9, 1), date(2026, 9, 2))
