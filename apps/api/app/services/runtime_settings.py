from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models import AppSetting

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


# Readonly env keys whose raw values must never be exposed
_READONLY_SECRET_KEYS = frozenset({
    "jwt_secret",
    "database_url",
    "redis_url",
    "celery_broker_url",
    "celery_result_backend",
})


def build_settings_response(
    merged: dict[str, Any],
    row: AppSetting | None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Build the public settings payload with masked secrets."""
    settings = get_settings()

    editable: dict[str, Any] = {}
    for key, value in merged.items():
        if key in SECRET_KEYS:
            editable[key] = mask_secret(value)
        else:
            editable[key] = value

    readonly: dict[str, Any] = {
        "app_env": settings.app_env,
        "jwt_secret": mask_secret(settings.jwt_secret),
        "jwt_expire_hours": settings.jwt_expire_hours,
        "admin_username": settings.admin_username,
        "database_url": mask_secret(settings.database_url),
        "redis_url": mask_secret(settings.redis_url),
        "celery_broker_url": mask_secret(settings.celery_broker_url),
        "celery_result_backend": mask_secret(settings.celery_result_backend),
        "sources_config_path": settings.sources_config_path,
    }

    meta: dict[str, Any] = {
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
        "updated_by": str(row.updated_by) if row and row.updated_by else None,
    }

    return {
        "editable": editable,
        "readonly": readonly,
        "meta": meta,
        "warnings": warnings or [],
    }


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


_cache: dict[str, Any] | None = None


def invalidate_cache() -> None:
    global _cache
    _cache = None


def get_cached_merged() -> dict[str, Any] | None:
    return _cache


async def ensure_seeded(session: AsyncSession) -> AppSetting:
    row = await session.get(AppSetting, 1)
    if row:
        return row
    row = AppSetting(id=1, values=defaults_from_env(get_settings()))
    session.add(row)
    await session.commit()
    await session.refresh(row)
    invalidate_cache()
    return row


async def get_merged(session: AsyncSession) -> dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    row = await ensure_seeded(session)
    env_defaults = defaults_from_env(get_settings())
    _cache = merge_values(env_defaults, row.values or {})
    return _cache


async def update_settings(
    session: AsyncSession,
    patch: dict[str, Any],
    user_id: uuid.UUID | None,
) -> tuple[dict[str, Any], list[str], AppSetting]:
    row = await ensure_seeded(session)
    env_defaults = defaults_from_env(get_settings())
    current = merge_values(env_defaults, row.values or {})
    new_values, warnings = apply_patch(current, patch)
    # Persist only editable bag (full merged editable snapshot)
    row.values = {k: new_values[k] for k in EDITABLE_KEYS if k in new_values}
    row.updated_by = user_id
    await session.commit()
    await session.refresh(row)
    invalidate_cache()
    merged = await get_merged(session)
    return merged, warnings, row
