from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: str
    username: str
    role: str
    auth_provider: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    knowledge_source: str = "local"
    locale: str = "zh-HK"


class DocumentOut(BaseModel):
    id: str
    source_id: str
    title: str
    circular_no: str | None
    issued_at: str | None
    language: str
    source_url: str
    file_url: str | None
    status: str
    file_size: int
    index_error: str | None = None
    warning: str | None = None


class DocumentVariantOut(BaseModel):
    id: str
    language: str
    status: str
    file_size: int
    title: str


class DocumentGroupOut(BaseModel):
    """One circular (or standalone doc) with zh/en/sc variants in the same box."""

    key: str
    title: str
    circular_no: str | None
    issued_at: str | None
    source_id: str
    primary_id: str
    variants: list[DocumentVariantOut]


class SecretFieldOut(BaseModel):
    configured: bool
    masked: str | None = None


class SettingsMeta(BaseModel):
    updated_at: str | None = None
    updated_by: str | None = None


class SettingsResponse(BaseModel):
    editable: dict[str, Any]
    readonly: dict[str, Any]
    meta: SettingsMeta
    warnings: list[str] = []


class SettingsUpdate(BaseModel):
    """Partial update of editable settings. Unknown keys and extras are rejected."""

    model_config = ConfigDict(extra="forbid")

    app_name: str | None = None
    cors_origins: str | None = None
    llm_provider: str | None = None
    openrouter_api_key: str | None = None
    openrouter_model: str | None = None
    openrouter_base_url: str | None = None
    ollama_base_url: str | None = None
    ollama_model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    system_prompt: str | None = None
    cite_inline_refs: bool | None = None
    local_top_k: int | None = None
    dify_top_k: int | None = None
    jina_api_key: str | None = None
    jina_embedding_model: str | None = None
    jina_embedding_dim: int | None = None
    dify_enabled: bool | None = None
    dify_api_url: str | None = None
    dify_dataset_api_key: str | None = None
    dify_app_api_key: str | None = None
    dify_dataset_id: str | None = None
    crawl_enabled: bool | None = None
    crawl_user_agent: str | None = None
    crawl_rate_limit_seconds: float | None = None
    storage_backend: str | None = None
    local_storage_path: str | None = None
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str | None = None
    minio_public_url: str | None = None
    minio_secure: bool | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
