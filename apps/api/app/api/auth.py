from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import LoginRequest, TokenResponse, UserOut
from app.core.db import get_db
from app.core.security import create_access_token, verify_password
from app.models.entities import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> TokenResponse:
    user = await db.scalar(select(User).where(User.username == body.username))
    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(str(user.id), extra={"username": user.username, "role": user.role})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(user: Annotated[User, Depends(get_current_user)]) -> UserOut:
    return UserOut(
        id=str(user.id),
        username=user.username,
        role=user.role,
        auth_provider=user.auth_provider,
    )


@router.post("/logout")
async def logout(user: Annotated[User, Depends(get_current_user)]) -> dict:
    # JWT is stateless; client discards token.
    return {"ok": True, "username": user.username}
