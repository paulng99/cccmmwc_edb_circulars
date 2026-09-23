from __future__ import annotations

from typing import Any

from app.core.config import Settings

DEFAULT_SYSTEM_PROMPT = """You are an assistant for Hong Kong Education Bureau (EDB) circulars and documents.
Answer in the same language as the user (prefer Traditional Chinese zh-HK when the user writes Chinese).
Use ONLY the provided context. If unsure, say you cannot find it in the retrieved materials.
Always cite circular numbers and issue dates (yyyy-mm-dd) when available.
Do not invent policies or dates.
"""

SECRET_KEYS = frozenset({
    "openrouter_api_key",
    "jina_api_key",
    "dify_dataset_api_key",
    "dify_app_api_key",
    "minio_access_key",
    "minio_secret_key",
    "google_client_secret",
})

# Full editable key list per spec — include every key from design editable schema
EDITABLE_KEYS = frozenset({
    "app_name", "cors_origins",
    "llm_provider", "openrouter_api_key", "openrouter_model", "openrouter_base_url",
    "ollama_base_url", "ollama_model", "temperature", "max_tokens",
    "system_prompt", "cite_inline_refs", "local_top_k", "dify_top_k",
    "jina_api_key", "jina_embedding_model", "jina_embedding_dim",
    "dify_enabled", "dify_api_url", "dify_dataset_api_key", "dify_app_api_key", "dify_dataset_id",
    "crawl_enabled", "crawl_user_agent", "crawl_rate_limit_seconds",
    "storage_backend", "local_storage_path",
    "minio_endpoint", "minio_access_key", "minio_secret_key", "minio_bucket",
    "minio_public_url", "minio_secure",
    "google_client_id", "google_client_secret",
})

INLINE_CITE_INSTRUCTION = (
    "When using a context block, include its reference tag "
    "(e.g. [L1], [D2]) inline next to the claim."
)


def mask_secret(value: str | None) -> dict[str, Any]:
    if not value:
        return {"configured": False, "masked": None}
    tail = value[-4:] if len(value) >= 4 else value
    return {"configured": True, "masked": f"••••{tail}"}


def defaults_from_env(settings: Settings) -> dict[str, Any]:
    return {
        "app_name": settings.app_name,
        "cors_origins": settings.cors_origins,
        "llm_provider": settings.llm_provider,
        "openrouter_api_key": settings.openrouter_api_key,
        "openrouter_model": settings.openrouter_model,
        "openrouter_base_url": settings.openrouter_base_url,
        "ollama_base_url": settings.ollama_base_url,
        "ollama_model": settings.ollama_model,
        "temperature": 0.2,
        "max_tokens": 4096,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "cite_inline_refs": True,
        "local_top_k": 8,
        "dify_top_k": 5,
        "jina_api_key": settings.jina_api_key,
        "jina_embedding_model": settings.jina_embedding_model,
        "jina_embedding_dim": settings.jina_embedding_dim,
        "dify_enabled": settings.dify_enabled,
        "dify_api_url": settings.dify_api_url,
        "dify_dataset_api_key": settings.dify_dataset_api_key,
        "dify_app_api_key": settings.dify_app_api_key,
        "dify_dataset_id": settings.dify_dataset_id,
        "crawl_enabled": settings.crawl_enabled,
        "crawl_user_agent": settings.crawl_user_agent,
        "crawl_rate_limit_seconds": settings.crawl_rate_limit_seconds,
        "storage_backend": settings.storage_backend,
        "local_storage_path": settings.local_storage_path,
        "minio_endpoint": settings.minio_endpoint,
        "minio_access_key": settings.minio_access_key,
        "minio_secret_key": settings.minio_secret_key,
        "minio_bucket": settings.minio_bucket,
        "minio_public_url": settings.minio_public_url,
        "minio_secure": settings.minio_secure,
        "google_client_id": settings.google_client_id,
        "google_client_secret": settings.google_client_secret,
    }


def merge_values(env_defaults: dict[str, Any], db_values: dict[str, Any]) -> dict[str, Any]:
    out = dict(env_defaults)
    for k, v in (db_values or {}).items():
        if k in EDITABLE_KEYS:
            out[k] = v
    return out


def apply_patch(current: dict[str, Any], patch: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    unknown = set(patch) - EDITABLE_KEYS
    if unknown:
        raise ValueError(f"Unknown settings keys: {sorted(unknown)}")
    new = dict(current)
    warnings: list[str] = []
    for k, v in patch.items():
        if k in SECRET_KEYS and (v is None or v == ""):
            continue
        if k == "jina_embedding_dim" and v != current.get("jina_embedding_dim"):
            warnings.append("reindex_required")
        if k == "temperature":
            if not isinstance(v, (int, float)) or not (0 <= float(v) <= 2):
                raise ValueError("temperature must be between 0 and 2")
            v = float(v)
        if k in ("max_tokens", "local_top_k", "dify_top_k", "jina_embedding_dim"):
            if not isinstance(v, int) or v < 1:
                raise ValueError(f"{k} must be int >= 1")
        if k == "llm_provider" and v not in ("openrouter", "ollama"):
            raise ValueError("llm_provider must be openrouter or ollama")
        if k == "storage_backend" and v not in ("local", "minio"):
            raise ValueError("storage_backend must be local or minio")
        new[k] = v
    return new, warnings
