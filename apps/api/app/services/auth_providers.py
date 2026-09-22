"""Auth provider seam — password now; Google OAuth later."""

from __future__ import annotations

from typing import Protocol

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_access_token, verify_password
from app.models.entities import User


class AuthProvider(Protocol):
    async def authenticate(self, db: AsyncSession, **kwargs) -> User: ...


class PasswordAuthProvider:
    async def authenticate(self, db: AsyncSession, **kwargs) -> User:
        username = kwargs.get("username") or ""
        password = kwargs.get("password") or ""
        user = await db.scalar(select(User).where(User.username == username))
        if not user or not user.password_hash or not verify_password(password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        return user


class GoogleOAuthProvider:
    """Stub for phase-2 Google login. Configure GOOGLE_CLIENT_ID to enable."""

    async def authenticate(self, db: AsyncSession, **kwargs) -> User:
        settings = get_settings()
        if not settings.google_client_id:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Google OAuth not configured (set GOOGLE_CLIENT_ID)",
            )
        # Future: verify id_token with Google, upsert User(google_sub=..., auth_provider="google")
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google OAuth coming in a later release",
        )


def issue_token(user: User) -> str:
    return create_access_token(
        str(user.id),
        extra={"username": user.username, "role": user.role, "auth_provider": user.auth_provider},
    )


def get_password_auth() -> PasswordAuthProvider:
    return PasswordAuthProvider()


def get_google_auth() -> GoogleOAuthProvider:
    return GoogleOAuthProvider()
