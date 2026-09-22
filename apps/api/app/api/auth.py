from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import LoginRequest, TokenResponse, UserOut
from app.core.db import get_db
from app.models.entities import User
from app.services.auth_providers import get_google_auth, get_password_auth, issue_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


class GoogleLoginRequest(BaseModel):
    id_token: str


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> TokenResponse:
    user = await get_password_auth().authenticate(db, username=body.username, password=body.password)
    return TokenResponse(access_token=issue_token(user))


@router.post("/google", response_model=TokenResponse)
async def login_google(body: GoogleLoginRequest, db: Annotated[AsyncSession, Depends(get_db)]) -> TokenResponse:
    user = await get_google_auth().authenticate(db, id_token=body.id_token)
    return TokenResponse(access_token=issue_token(user))


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
    return {"ok": True, "username": user.username}
