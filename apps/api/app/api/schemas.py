from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class ChatAttachmentIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    text: str = Field(default="", max_length=20000)


class ChatRequest(BaseModel):
    question: str = Field(default="", max_length=4000)
    session_id: str | None = None
    knowledge_source: str = "local"
    locale: str = "zh-HK"
    programme: str | None = None
    topic: str | None = None
    focus_document_id: str | None = None
    attachments: list[ChatAttachmentIn] = Field(default_factory=list, max_length=3)

    @field_validator("focus_document_id", mode="before")
    @classmethod
    def normalize_focus_document_id(cls, value: Any) -> str | None:
        if value is None or value == "":
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            return str(uuid.UUID(text))
        except (ValueError, TypeError) as exc:
            raise ValueError("focus_document_id must be a valid UUID") from exc


class ChatAttachmentOut(BaseModel):
    filename: str
    char_count: int = 0


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    truncated: bool = False
    knowledge_source: str = "local"
    programme: str | None = None
    topic: str | None = None
    prompt_only: bool = False
    web_fallback: bool = False
    attachments: list[ChatAttachmentOut] = Field(default_factory=list)


class DocumentActivityOut(BaseModel):
    name: str | None = None
    starts_at: str | None = None
    deadline_at: str | None = None
    summary: str | None = None
    location: str | None = None


class DocumentOut(BaseModel):
    id: str
    source_id: str
    title: str
    circular_no: str | None
    issued_at: str | None
    revised_at: str | None = None
    downloaded_at: str | None = None
    activities: list[DocumentActivityOut] = Field(default_factory=list)
    language: str
    source_url: str
    file_url: str | None
    status: str
    file_size: int
    chunk_count: int = 0
    programme: str = "other"
    topics: list[str] = []
    index_error: str | None = None
    warning: str | None = None
    # LLM "what the school should do" paragraph; not calendar activity summary.
    school_action: str | None = None


class ReanalyzeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


class ReanalyzeItemOut(BaseModel):
    document_id: str
    ok: bool
    school_action: str | None = None
    error: str | None = None
    message: str | None = None


class ReanalyzeResponse(BaseModel):
    results: list[ReanalyzeItemOut]


class CalendarEventOut(BaseModel):
    date: str
    kind: str  # start | deadline
    activity_name: str | None = None
    summary: str | None = None
    location: str | None = None
    document_id: str
    document_title: str
    circular_no: str | None = None


class CalendarDayOut(BaseModel):
    date: str
    events: list[CalendarEventOut] = Field(default_factory=list)


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
    revised_at: str | None = None
    downloaded_at: str | None = None
    source_id: str
    primary_id: str
    programme: str = "other"
    category: str = "document"  # legacy: circular | document
    topics: list[str] = []
    variants: list[DocumentVariantOut]
    school_action: str | None = None


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
    defaults: dict[str, Any] = Field(default_factory=dict)


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
    llm_top_p: float | None = None
    system_prompt: str | None = None
    cite_inline_refs: bool | None = None
    local_top_k: int | None = None
    local_min_score: float | None = None
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

    @field_validator("llm_top_p", mode="before")
    @classmethod
    def normalize_llm_top_p(cls, value: Any) -> Any:
        """空字串視為清除；布林值不可隱式轉成 0／1。"""
        if value == "":
            return None
        if isinstance(value, bool):
            raise ValueError("llm_top_p must be a number between 0 and 1")
        return value


class SourcesConfigBody(BaseModel):
    sources: list[dict[str, Any]]


class SourceSuggestBody(BaseModel):
    mode: str
    query: str = Field(min_length=1, max_length=500)


class ImproveSystemPromptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=50000)
