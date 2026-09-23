from __future__ import annotations

from pydantic import BaseModel, Field


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
